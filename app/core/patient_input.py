"""手で入れた患者の値の確かめ（docs/spec/01_orders.md 3.4）.

画面・CLI が使う Pure な処理。誤りは日本語の文で `ValidationError` にする。文は入れた値を
含めない。規則の原典：

- 氏名（PN）：DICOM PS3.5 6.2。1つの成分グループは 64 字まで、成分は 5 つまで。`=`（群の
  区切り）・`\\`（値の区切り）・制御文字は使えない。英字の群は基本の文字集合（ISO 646）に収める
- 患者ID：PS3.5 6.2 の LO（64 字まで）。HL7 v2 の PID-3 にエスケープなしで入れるため、
  基本の文字集合の表示できる字に限り、HL7 v2 の区切り（`^~&|`）と前後の空白も断る
- 生年月日：PS3.5 6.2 の DA（YYYYMMDD）。暦にある日で、今日より後は断る
- 性別：PS3.3 C.7.1.1 の Patient's Sex（M・F・O。空は許す）

漢字の氏名は、予約の文字コード（設定の `orders.default_character_set`）で表せる字だけを受ける。
UTF-8 なら制限しない。かなの氏名は全角カタカナだけを受け、ひらがなはカタカナに直す。半角カナは
断る。試験の形（設定の `orders.patient_input_test_mode`）では、かなの確かめと直しをせず、
そのまま通す。
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.core.charset import unencodable_chars
from app.core.exceptions import ValidationError
from app.core.models import (
    CHARACTER_SET_TERMS,
    HL7_V2_DELIMITERS,
    LO_MAX_LENGTH,
    PN_GROUP_MAX_LENGTH,
    CharacterSet,
    Patient,
    PersonName,
    has_control_chars,
)

PN_COMPONENT_MAX_COUNT = 5
SEX_VALUES = ("M", "F", "O")
SCRIPT_LABELS = {"alphabetic": "英字", "ideographic": "漢字", "phonetic": "かな"}
_ASCII_PRINTABLE_MIN = 0x20
_ASCII_PRINTABLE_MAX = 0x7E
_ALPHABETIC_COMPONENT = re.compile(r"[A-Za-z' -]*")
_DATE = re.compile(r"[0-9]{8}")
# 全角カタカナ（ァ〜ヺ）・中点・長音・繰り返し記号・空白（半角と全角 U+3000）。成分の区切り
# `^` は群の中で許す
_KATAKANA = re.compile(r"[ァ-ヺ・-ヾ 　]*")
_HIRAGANA_TO_KATAKANA_OFFSET = 0x60
_HIRAGANA_RANGES = ((0x3041, 0x3096), (0x309D, 0x309E))
# 半角カナ。jis_kana の ISO 2022 IR 13 は表せるが、RIS は漢字の氏名に半角カナを入れない
# （画面は jis・jis_kana のどちらでも断る。docs/spec/01_orders.md の 3.4）
_HALFWIDTH_KANA = re.compile("[｡-ﾟ]")

# 画面のスクリプトも同じ文を出す（入力した時に分かるように。app/web/static/app.js）
ALPHABETIC_MESSAGE = "氏名（英字）は半角の英字・空白・ハイフン・アポストロフィで入力してください。"
IDEOGRAPHIC_MESSAGE = (
    "氏名（漢字）に、この文字コードでは表せない字があります。"
    "文字コードを UTF-8 にするか、表せる字に入れ替えてください。"
)
PHONETIC_MESSAGE = "氏名（かな）は全角のカタカナで入力してください。"
PHONETIC_CONVERTED_NOTE = "ひらがなをカタカナに直しました。"
PATIENT_ID_MESSAGE = "患者ID は半角の英数字と記号で入力してください（\\ ^ ~ & | は使えません）。"
BIRTH_DATE_FUTURE_MESSAGE = "生年月日は今日以前の日付を入力してください。"
# 欄の確かめの種類（data-check）ごとの文
INPUT_MESSAGES = {
    "patient-id": PATIENT_ID_MESSAGE,
    "alphabetic": ALPHABETIC_MESSAGE,
    "ideographic": IDEOGRAPHIC_MESSAGE,
    "phonetic": PHONETIC_MESSAGE,
    "birth-date": BIRTH_DATE_FUTURE_MESSAGE,
}


def validate_patient_input(
    patient: Patient,
    today: date | None = None,
    character_set: CharacterSet = CharacterSet.UTF8,
    *,
    test_mode: bool = False,
) -> None:
    """手で入れた患者の値を確かめる。誤りは `ValidationError`（最初の1件）."""
    validate_patient_id_input(patient.patient_id)
    validate_person_name(patient.name, character_set, test_mode=test_mode)
    validate_birth_date(patient.birth_date, today)
    validate_sex(patient.sex)


def validate_patient_id_input(value: str) -> None:
    """患者ID：1〜64 字、表示できる ASCII、`\\` と HL7 v2 の区切り無し、前後の空白無し."""
    if not value.strip():
        raise ValidationError("患者ID を入力してください。")
    if len(value) > LO_MAX_LENGTH:
        raise ValidationError(f"患者ID は {LO_MAX_LENGTH} 字以内で入力してください。")
    if value != value.strip():
        raise ValidationError("患者ID の前後の空白を消してください。")
    if (
        any(not _ASCII_PRINTABLE_MIN <= ord(char) <= _ASCII_PRINTABLE_MAX for char in value)
        or "\\" in value
        or any(char in HL7_V2_DELIMITERS for char in value)
    ):
        raise ValidationError(PATIENT_ID_MESSAGE)


def validate_person_name(
    name: PersonName,
    character_set: CharacterSet = CharacterSet.UTF8,
    *,
    test_mode: bool = False,
) -> None:
    """氏名の3つの群を、群ごとに確かめる."""
    for script, label in SCRIPT_LABELS.items():
        message = check_name_group(
            script, label, getattr(name, script), character_set, test_mode=test_mode
        )
        if message:
            raise ValidationError(message)


def check_name_component(label: str, text: str) -> str:
    """画面の姓・名の1つの欄の誤りの文。姓と名の区切り（`^`）は欄に入れられない."""
    if any(char in text for char in "^=\\") or has_control_chars(text):
        return f"氏名（{label}）に ^ = \\ と制御文字は使えません。姓と名は別の欄に入れてください。"
    return ""


def check_name_group(
    script: str,
    label: str,
    group: str,
    character_set: CharacterSet = CharacterSet.UTF8,
    *,
    test_mode: bool = False,
) -> str:
    """氏名の1つの群の誤りの文。誤りが無ければ空（群は `^` で成分に区切った後の形）."""
    if len(group) > PN_GROUP_MAX_LENGTH:
        return f"氏名（{label}）は {PN_GROUP_MAX_LENGTH} 字以内で入力してください。"
    if has_control_chars(group) or "\\" in group or "=" in group:
        return f"氏名（{label}）に使えない字があります。= \\ と制御文字を消してください。"
    if len(group.split("^")) > PN_COMPONENT_MAX_COUNT:
        return f"氏名（{label}）の姓と名の区切りは {PN_COMPONENT_MAX_COUNT} つまでです。"
    if script == "alphabetic":
        return check_alphabetic_group(group)
    if script == "ideographic":
        return check_ideographic_group(group, character_set)
    return check_phonetic_group(group, test_mode=test_mode)


def check_alphabetic_group(group: str) -> str:
    """英字の氏名：半角の英字・空白・ハイフン・アポストロフィだけ（`^` は成分の区切り）."""
    if all(_ALPHABETIC_COMPONENT.fullmatch(part) for part in group.split("^")):
        return ""
    return ALPHABETIC_MESSAGE


def check_ideographic_group(group: str, character_set: CharacterSet = CharacterSet.UTF8) -> str:
    """漢字の氏名：予約の文字コードで表せる字だけ。UTF-8 なら制限しない."""
    if character_set == CharacterSet.UTF8:
        return ""
    if _HALFWIDTH_KANA.search(group) or unencodable_chars(group, CHARACTER_SET_TERMS[character_set]):
        return IDEOGRAPHIC_MESSAGE
    return ""


def check_phonetic_group(group: str, *, test_mode: bool = False) -> str:
    """かなの氏名：全角カタカナ（長音・中点・空白・`^` 区切りを含む）だけ。半角カナは断る.

    ひらがなは `to_katakana` でカタカナに直してから確かめる。試験の形では何も見ずに通す。
    """
    if test_mode:
        return ""
    if all(_KATAKANA.fullmatch(part) for part in group.split("^")):
        return ""
    return PHONETIC_MESSAGE


def to_katakana(text: str) -> str:
    """ひらがな（ゝゞを含む）を全角カタカナにする。ほかの字は変えない."""
    return "".join(
        chr(ord(char) + _HIRAGANA_TO_KATAKANA_OFFSET)
        if any(low <= ord(char) <= high for low, high in _HIRAGANA_RANGES)
        else char
        for char in text
    )


def validate_birth_date(value: str, today: date | None = None) -> None:
    """生年月日：空か、暦にある YYYYMMDD で今日以前."""
    if not value:
        return
    parsed = None
    if _DATE.fullmatch(value):
        try:
            parsed = datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            parsed = None
    if parsed is None:
        raise ValidationError("生年月日は、暦にある日付を入力してください。")
    if parsed > (today or date.today()):
        raise ValidationError(BIRTH_DATE_FUTURE_MESSAGE)


def validate_sex(value: str) -> None:
    if value and value not in SEX_VALUES:
        raise ValidationError("性別は、M・F・O のどれかを選んでください。")
