"""手で入れた患者の値の確かめ（docs/spec/01_orders.md 3.3）.

画面・CLI・サービスが使う Pure な処理。誤りは日本語の文で `ValidationError` にする。文は
入れた値を含めない。規則の原典：

- 氏名（PN）：DICOM PS3.5 6.2。1つの成分グループは 64 字まで、成分は 5 つまで。`=`（群の
  区切り）・`\\`（値の区切り）・制御文字は使えない。英字の群は基本の文字集合（ISO 646）に収める
- 患者ID：PS3.5 6.2 の LO（64 字まで）。HL7 v2 の PID-3 にエスケープなしで入れるため、
  基本の文字集合の表示できる字に限り、HL7 v2 の区切り（`^~&|`）と前後の空白も断る
- 生年月日：PS3.5 6.2 の DA（YYYYMMDD）。暦にある日で、今日より後は断る
- 性別：PS3.3 C.7.1.1 の Patient's Sex（M・F・O。空は許す）
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.core.exceptions import ValidationError
from app.core.models import (
    HL7_V2_DELIMITERS,
    LO_MAX_LENGTH,
    PN_GROUP_MAX_LENGTH,
    Patient,
    PersonName,
    has_control_chars,
)

PN_COMPONENT_MAX_COUNT = 5
SEX_VALUES = ("M", "F", "O")
SCRIPT_LABELS = {"alphabetic": "英字", "ideographic": "漢字", "phonetic": "かな"}
_ASCII_PRINTABLE_MIN = 0x20
_ASCII_PRINTABLE_MAX = 0x7E
_ASCII_MAX = 0x7F
_ALPHABETIC_COMPONENT = re.compile(r"[A-Za-z' -]*")
_DATE = re.compile(r"[0-9]{8}")
_JIS_X_0208_ESCAPES = (b"\x1b$B", b"\x1b$@")

# 画面のスクリプトも同じ文を出す（入力した時に分かるように。app/web/static/app.js）
ALPHABETIC_MESSAGE = "氏名（英字）は半角の英字・空白・ハイフン・アポストロフィで入力してください。"
IDEOGRAPHIC_MESSAGE = "氏名（漢字）に使えない字があります。日本語の漢字・ひらがな・カタカナで入力し直してください。"
PATIENT_ID_MESSAGE = "患者ID は半角の英数字と記号で入力してください（\\ ^ ~ & | は使えません）。"
BIRTH_DATE_FUTURE_MESSAGE = "生年月日は今日以前の日付を入力してください。"
# 欄の確かめの種類（data-check）ごとの文
INPUT_MESSAGES = {
    "patient-id": PATIENT_ID_MESSAGE,
    "alphabetic": ALPHABETIC_MESSAGE,
    "ideographic": IDEOGRAPHIC_MESSAGE,
    "birth-date": BIRTH_DATE_FUTURE_MESSAGE,
}


def validate_patient_input(patient: Patient, today: date | None = None) -> None:
    """手で入れた患者の値を確かめる。誤りは `ValidationError`（最初の1件）."""
    validate_patient_id_input(patient.patient_id)
    validate_person_name(patient.name)
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


def validate_person_name(name: PersonName) -> None:
    """氏名の3つの群を、群ごとに確かめる."""
    for script, label in SCRIPT_LABELS.items():
        message = check_name_group(script, label, getattr(name, script))
        if message:
            raise ValidationError(message)


def check_name_component(label: str, text: str) -> str:
    """画面の姓・名の1つの欄の誤りの文。姓と名の区切り（`^`）は欄に入れられない."""
    if any(char in text for char in "^=\\") or has_control_chars(text):
        return f"氏名（{label}）に ^ = \\ と制御文字は使えません。姓と名は別の欄に入れてください。"
    return ""


def check_name_group(script: str, label: str, group: str) -> str:
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
        return check_ideographic_group(group)
    return check_phonetic_group(group)


def check_alphabetic_group(group: str) -> str:
    """英字の氏名：半角の英字・空白・ハイフン・アポストロフィだけ（`^` は成分の区切り）."""
    if all(_ALPHABETIC_COMPONENT.fullmatch(part) for part in group.split("^")):
        return ""
    return ALPHABETIC_MESSAGE


def check_ideographic_group(group: str) -> str:
    """漢字の氏名：JIS X 0208 で表せる字（と ASCII）。半角カナや JIS に無い字は断る."""
    return "" if all(_is_ideographic_char(char) for char in group) else IDEOGRAPHIC_MESSAGE


def check_phonetic_group(group: str) -> str:
    """かなの氏名。ひらがな・カタカナ・半角カナのどれを許すかは未決のため、今は文字の種類を見ない.

    決まったら、ここに規則を足す（群の長さと禁止の字は `check_name_group` で確かめ済み）。
    """
    return ""


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


def _is_ideographic_char(char: str) -> bool:
    if ord(char) <= _ASCII_MAX:
        return True
    try:
        encoded = char.encode("iso2022_jp")
    except UnicodeEncodeError:
        return False
    return any(escape in encoded for escape in _JIS_X_0208_ESCAPES)
