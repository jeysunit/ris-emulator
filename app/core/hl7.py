"""HL7 v2.3.1 のメッセージの組み立てと ACK の読み取り（docs/spec/06_hl7_pir.md）.

IHE RAD TF-2 の Patient Update [RAD-12]（ADT^A08・ADT^A40）と Procedure Scheduled
[RAD-4]（ORM^O01）を組み立てる。ファイル・通信を使わない。通信は `app/hl7/mllp.py`。
値は 1 つずつ `escape` を通してから区切り文字でつなぐ。
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from app.core.exceptions import AckParseError, ValidationError
from app.core.models import Order, Patient, PersonName, has_control_chars, validate_patient_id

SEGMENT_SEPARATOR = "\r"
FIELD_SEPARATOR = "|"
ENCODING_CHARACTERS = "^~\\&"
HL7_VERSION = "2.3.1"
# IHE RAD TF-2 2.4.4.2 の MSH-18 の例にある値。MSH-20（文字集合の切り替え）は IHE が認めない
UTF8_CHARACTER_SET = "UNICODE UTF-8"
CONTROL_ID_LENGTH = 20
PATIENT_CLASS_PATTERN = re.compile(r"[A-Z0-9]")
# DICOM の PN のコンポーネント（姓・名・ミドル・接頭辞・接尾辞）の数
_PN_COMPONENTS = 5
_ORDER_PRIORITY = {"STAT": "S", "HIGH": "A", "ROUTINE": "R"}
_ESCAPES = (
    ("\\", "\\E\\"),
    ("|", "\\F\\"),
    ("^", "\\S\\"),
    ("&", "\\T\\"),
    ("~", "\\R\\"),
)
_SEGMENT_SPLIT = re.compile(r"[\r\n]+")


@dataclass(frozen=True)
class Hl7Header:
    """MSH に入れる送り手と受け手の名前（HD の namespace ID）と処理区分."""

    sending_application: str
    sending_facility: str
    receiving_application: str
    receiving_facility: str
    processing_id: str = "P"


@dataclass(frozen=True)
class Hl7Message:
    """組み立てた 1 通のメッセージ。`text` は区切りが CR の HL7 のテキスト."""

    message_type: str  # 例 ADT^A40
    control_id: str
    text: str

    def to_bytes(self) -> bytes:
        return self.text.encode("utf-8")

    def display(self) -> str:
        """人が読むために、セグメントの区切りの CR を改行にしたもの."""
        return self.text.replace(SEGMENT_SEPARATOR, "\n")


@dataclass(frozen=True)
class Ack:
    """受け取った ACK の MSA（と ERR）の内容."""

    code: str  # MSA-1
    control_id: str  # MSA-2
    text: str  # MSA-3（エスケープを戻した値）
    error: str  # ERR-1（そのままの値）


def escape(value: str) -> str:
    """HL7 v2 の区切り文字（`| ^ ~ & \\`）を、エスケープシーケンス（`\\F\\ \\S\\ \\R\\ \\T\\ \\E\\`）にする.

    CR・LF・タブなどの制御文字はセグメントの区切りや MLLP の枠と混ざるので断る。
    """
    if has_control_chars(value):
        raise ValidationError("HL7 の値に制御文字は入れられません", {"value": repr(value)})
    for char, sequence in _ESCAPES:
        value = value.replace(char, sequence)
    return value


def unescape(value: str, encoding_characters: str = ENCODING_CHARACTERS) -> str:
    """`escape` で作ったシーケンスを元の文字に戻す。ほかのシーケンス（`\\.br\\` など）は触らない."""
    if len(encoding_characters) < 4:
        return value
    component, repetition, escape_char, subcomponent = encoding_characters[:4]
    table = {
        "F": FIELD_SEPARATOR,
        "S": component,
        "T": subcomponent,
        "R": repetition,
        "E": escape_char,
    }
    pattern = re.compile(re.escape(escape_char) + "([FSTRE])" + re.escape(escape_char))
    return pattern.sub(lambda match: table[match.group(1)], value)


def new_control_id(now: datetime) -> str:
    """MSH-10：`yyMMddHHmmss` に乱数 8 桁（16 進）を足した 20 文字（MSH-10 は 20 文字まで）."""
    return now.strftime("%y%m%d%H%M%S") + secrets.token_hex(4)


def build_adt_a08(
    header: Hl7Header,
    patient: Patient,
    *,
    namespace: str,
    visit_number: str = "",
    account_number: str = "",
    patient_class: str = "O",
    now: datetime | None = None,
    control_id: str | None = None,
) -> Hl7Message:
    """ADT^A08^ADT_A08（患者の属性の更新。IHE RAD TF-2 4.12.4.3）.

    PID-3 の患者 ID は更新できない（A40 を使う）。PID-18 か PV1-19 のどちらかが要る。
    """
    _require_visit_or_account(visit_number, account_number)
    when = now or datetime.now()
    body = [
        segment("EVN", {1: "A08", 2: hl7_timestamp(when)}),
        _pid(patient, namespace, account_number),
        _pv1(patient_class, visit_number, namespace),
    ]
    return _assemble(header, "ADT", "A08", "ADT_A08", body, when, control_id)


def build_adt_a40(
    header: Hl7Header,
    patient: Patient,
    *,
    namespace: str,
    prior_patient_id: str,
    prior_name: PersonName | None = None,
    now: datetime | None = None,
    control_id: str | None = None,
) -> Hl7Message:
    """ADT^A40^ADT_A39（患者 ID の統合。PID が正式の患者、MRG が旧い患者。TF-2 4.12.4.4）.

    PV1 は任意なので付けない。旧い患者の氏名（MRG-7）は、渡されたときだけ付ける。
    """
    if not prior_patient_id:
        raise ValidationError("統合する旧い患者 ID が要ります")
    try:
        validate_patient_id(prior_patient_id)
    except ValueError as exc:
        raise ValidationError(f"旧い患者 ID が使えません：{exc}", {"value": prior_patient_id}) from exc
    if prior_patient_id == patient.patient_id:
        raise ValidationError("旧い患者 ID が正式の患者 ID と同じです。属性の更新は A08 を使います")
    when = now or datetime.now()
    body = [
        segment("EVN", {1: "A40", 2: hl7_timestamp(when)}),
        _pid(patient, namespace, ""),
        segment(
            "MRG",
            {1: _cx(prior_patient_id, namespace, "PI"), 7: _xpn_list(prior_name or PersonName())},
        ),
    ]
    return _assemble(header, "ADT", "A40", "ADT_A39", body, when, control_id)


def build_orm_o01(
    header: Hl7Header,
    order: Order,
    *,
    visit_number: str,
    patient_class: str = "O",
    now: datetime | None = None,
    control_id: str | None = None,
) -> Hl7Message:
    """ORM^O01^ORM_O01（Procedure Scheduled。ORC-1 は NW。IHE RAD TF-2 4.4.4.1.2.1）.

    予約 1 件を ORC・OBR の 1 組にし、Study Instance UID を ZDS-1 に入れる。
    """
    _require_visit_or_account(visit_number, "")
    namespace = order.issuer_namespace
    when = now or datetime.now()
    start = order.scheduled_date + order.scheduled_time
    procedure = comp(escape(order.procedure.code), escape(order.procedure.name), escape(order.procedure.coding_scheme))
    filler_number = comp(escape(order.accession_number), escape(namespace))
    timing = comp("", "", "", start)
    ordering_provider = _xcn(order.requesting_physician)
    body = [
        _pid(order.patient, namespace, ""),
        _pv1(patient_class, visit_number, namespace, referring=order.referring_physician),
        segment(
            "ORC",
            {
                1: "NW",
                3: filler_number,
                5: "SC",
                7: timing,
                12: ordering_provider,
            },
        ),
        segment(
            "OBR",
            {
                1: "1",
                3: filler_number,
                4: comp(
                    escape(order.procedure.code),
                    escape(order.procedure.name),
                    escape(order.procedure.coding_scheme),
                    escape(order.procedure.code),
                    escape(order.procedure.name),
                    escape(order.procedure.coding_scheme),
                ),
                5: _ORDER_PRIORITY.get(order.priority, ""),
                16: ordering_provider,
                18: escape(order.accession_number),
                19: escape(order.requested_procedure_id),
                20: escape(order.scheduled_procedure_step_id),
                24: escape(order.modality),
                27: timing,
                44: procedure,
            },
        ),
        segment(
            "ZDS",
            {
                1: comp(
                    escape(order.study_instance_uid),
                    escape(header.sending_application),
                    "Application",
                    "DICOM",
                )
            },
        ),
    ]
    return _assemble(header, "ORM", "O01", "ORM_O01", body, when, control_id)


def segment(name: str, fields: dict[int, str]) -> str:
    """セグメント 1 つ。`fields` は欄の番号（1 から）と、エスケープ済みの値."""
    last = max(fields) if fields else 0
    return FIELD_SEPARATOR.join([name, *(fields.get(number, "") for number in range(1, last + 1))])


def comp(*parts: str) -> str:
    """コンポーネントをつなぐ。後ろの空は付けない。各部分はエスケープ済みの値."""
    values = list(parts)
    while values and not values[-1]:
        values.pop()
    return "^".join(values)


def hl7_timestamp(when: datetime) -> str:
    """TS：`YYYYMMDDHHMMSS`（時差は付けない。呼び出し側の時計の時刻のまま）."""
    return when.strftime("%Y%m%d%H%M%S")


def parse_ack(data: bytes | str) -> Ack:
    """ACK から MSA と ERR を読む。MSH・MSA が無い、区切りの定義が違うときは AckParseError."""
    text = data if isinstance(data, str) else data.decode("utf-8", errors="replace")
    segments = [part for part in _SEGMENT_SPLIT.split(text) if part]
    if not segments or not segments[0].startswith("MSH") or len(segments[0]) < 8:
        raise AckParseError("ACK の先頭が MSH ではありません")
    # IHE RAD TF-2 2.4.2.2：MSH-1・MSH-2 は HL7 の推奨値。違う定義の ACK は読まない
    separator = FIELD_SEPARATOR
    encoding_characters = ENCODING_CHARACTERS
    if not segments[0].startswith("MSH" + separator + encoding_characters + separator):
        raise AckParseError("ACK の MSH-1・MSH-2 が推奨値（|^~\\&）ではありません")
    msa = _find_segment(segments, "MSA", separator)
    if msa is None:
        raise AckParseError("ACK に MSA がありません")
    err = _find_segment(segments, "ERR", separator)
    # 相手が返した値は、端末・ログに出しても制御文字が働かないよう、見える形にして持つ
    return Ack(
        code=visible(_field(msa, 1)),
        control_id=visible(unescape(_field(msa, 2), encoding_characters)),
        text=visible(unescape(_field(msa, 3), encoding_characters)),
        error=visible(_field(err, 1) if err else ""),
    )


def visible(value: str) -> str:
    """制御文字（C0・DEL・C1）、書式文字（双方向の制御など）、行・段落の区切りを `\\uXXXX` にする.

    外から来た値を端末やログへ出すときの、エスケープシーケンスの注入と表示の偽装を防ぐ。
    """
    return "".join(
        f"\\u{ord(char):04x}" if unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") else char
        for char in value
    )


def _find_segment(segments: list[str], name: str, separator: str) -> list[str] | None:
    for item in segments:
        if item.startswith(name + separator):
            return item.split(separator)
    return None


def _field(fields: list[str], number: int) -> str:
    return fields[number] if number < len(fields) else ""


def _assemble(
    header: Hl7Header,
    family: str,
    event: str,
    structure: str,
    body: list[str],
    when: datetime,
    control_id: str | None,
) -> Hl7Message:
    identifier = control_id or new_control_id(when)
    if not identifier or len(identifier) > CONTROL_ID_LENGTH:
        raise ValidationError(f"MSH-10 は 1〜{CONTROL_ID_LENGTH} 文字にしてください")
    message_type = f"{family}^{event}"
    draft = _msh(header, f"{message_type}^{structure}", identifier, when, "")
    # IHE RAD TF-2 2.4.2.2：MSH-18 は ASCII 以外の文字を使うときだけ入れる
    character_set = "" if all(part.isascii() for part in [draft, *body]) else UTF8_CHARACTER_SET
    msh = _msh(header, f"{message_type}^{structure}", identifier, when, character_set)
    text = SEGMENT_SEPARATOR.join([msh, *body]) + SEGMENT_SEPARATOR
    return Hl7Message(message_type=message_type, control_id=identifier, text=text)


def _msh(header: Hl7Header, message_type: str, control_id: str, when: datetime, character_set: str) -> str:
    fields = {
        3: escape(header.sending_application),
        4: escape(header.sending_facility),
        5: escape(header.receiving_application),
        6: escape(header.receiving_facility),
        7: hl7_timestamp(when),
        9: message_type,
        10: escape(control_id),
        11: escape(header.processing_id),
        12: HL7_VERSION,
        18: character_set,
    }
    last = max(number for number, value in fields.items() if value)
    values = [fields.get(number, "") for number in range(3, last + 1)]
    # MSH-1 は区切り文字そのもの、MSH-2 は符号化文字
    return "MSH" + FIELD_SEPARATOR + ENCODING_CHARACTERS + FIELD_SEPARATOR + FIELD_SEPARATOR.join(values)


def _require_visit_or_account(visit_number: str, account_number: str) -> None:
    """IHE RAD TF-2 4.12.4.3.2.1.4・4.4.4.1.2.1.3：PID-18 か PV1-19 のどちらかに値が要る."""
    if not visit_number and not account_number:
        raise ValidationError("来院番号（PV1-19）か患者アカウント番号（PID-18）のどちらかが要ります")


def _pid(patient: Patient, namespace: str, account_number: str) -> str:
    if not _has_name(patient.name):
        raise ValidationError("PID-5 の患者名が空です")
    fields = {
        1: "1",
        3: _cx(patient.patient_id, namespace, "PI"),
        5: _xpn_list(patient.name),
        7: _birth_date(patient.birth_date),
        8: patient.sex,
    }
    if account_number:
        fields[18] = _cx(account_number, namespace, "AN")
    return segment("PID", fields)


def _pv1(patient_class: str, visit_number: str, namespace: str, *, referring: PersonName | None = None) -> str:
    if not PATIENT_CLASS_PATTERN.fullmatch(patient_class):
        raise ValidationError("PV1-2 の患者区分は英大文字か数字 1 文字にしてください", {"value": patient_class})
    fields = {1: "1", 2: patient_class}
    if referring is not None:
        fields[8] = _xcn(referring)
    if visit_number:
        fields[19] = _cx(visit_number, namespace, "VN")
        fields[51] = "V"
    return segment("PV1", fields)


def _cx(identifier: str, namespace: str, identifier_type: str) -> str:
    """CX：ID の値と Assigning Authority の namespace ID（IHE RAD TF-2 4.1.4.1.2.1.3 が必須とする）."""
    if not namespace:
        raise ValidationError(
            "PID-3 の Assigning Authority に入れる発番元が空です。"
            "設定の orders.issuer_namespace を空にしないでください"
        )
    return comp(escape(identifier), "", "", escape(namespace), identifier_type)


def _has_name(name: PersonName) -> bool:
    """氏名の成分のどれかに、空白以外の文字があるか（`^^^^` や空白だけは氏名にならない）."""
    groups = (name.alphabetic, name.ideographic, name.phonetic)
    return any(part.strip() for group in groups for part in group.split("^"))


def _birth_date(value: str) -> str:
    """PID-7：空か、実在する日付の `YYYYMMDD`（ASCII の数字 8 桁）."""
    if not value:
        return ""
    if not re.fullmatch(r"[0-9]{8}", value):
        raise ValidationError("生年月日は YYYYMMDD にしてください", {"value": repr(value)})
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValidationError("生年月日が実在する日付ではありません", {"value": value}) from exc
    return value


def _pn_components(group: str) -> list[str]:
    """DICOM の PN のコンポーネントグループを、姓・名・ミドル・接頭辞・接尾辞に分ける."""
    parts = group.split("^")
    if len(parts) > _PN_COMPONENTS:
        raise ValidationError("氏名のコンポーネントが 5 つを超えています", {"value": group})
    return [*parts, *[""] * (_PN_COMPONENTS - len(parts))]


def _xpn_list(name: PersonName) -> str:
    """XPN の繰り返し：英字・漢字・かなの順に、名前の種類 L（正式名）と表記の種類 A・I・P を付ける.

    DICOM の PN は 姓^名^ミドル^接頭辞^接尾辞、XPN は 姓^名^ミドル^接尾辞^接頭辞 の順なので、
    接頭辞と接尾辞を入れ替える。
    """
    repetitions = []
    for group, representation in (
        (name.alphabetic, "A"),
        (name.ideographic, "I"),
        (name.phonetic, "P"),
    ):
        if not group:
            continue
        family, given, middle, prefix, suffix = _pn_components(group)
        repetitions.append(
            comp(
                escape(family),
                escape(given),
                escape(middle),
                escape(suffix),
                escape(prefix),
                "",
                "L",
                representation,
            )
        )
    return "~".join(repetitions)


def _xcn(name: PersonName) -> str:
    """XCN：ID を持たない医師名。表記は 1 つだけ送る（英字があれば英字、無ければ漢字、かな）."""
    group = name.alphabetic or name.ideographic or name.phonetic
    if not group:
        return ""
    family, given, middle, prefix, suffix = _pn_components(group)
    return comp("", escape(family), escape(given), escape(middle), escape(suffix), escape(prefix))
