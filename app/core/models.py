"""予約（Order）と患者のモデル（docs/spec/01_orders.md）."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

AE_TITLE_MAX_LENGTH = 16
SH_MAX_LENGTH = 16
LO_MAX_LENGTH = 64
PN_GROUP_MAX_LENGTH = 64
UI_MAX_LENGTH = 64
HL7_V2_DELIMITERS = frozenset("^~&|")
# 性別は M・F・O・U の 4 値（医療システム共通）。U は不明で、DICOM の Patient's Sex には書かない
SEX_VALUES = ("M", "F", "O", "U")
SEX_UNKNOWN = "U"


def sex_from_dicom(value: str) -> str:
    """DICOM から読んだ性別。M・F・O 以外（空・規格外）は U（不明）."""
    return value if value in ("M", "F", "O") else SEX_UNKNOWN


def sex_to_dicom(value: str) -> str:
    """DICOM の Patient's Sex に書く値。列挙値は M・F・O だけなので、U は空にする."""
    return value if value in ("M", "F", "O") else ""


_DATE = re.compile(r"^\d{8}$")
_TIME = re.compile(r"^\d{6}$")
_PRINTABLE_ASCII_MIN = 0x20
_PRINTABLE_ASCII_MAX = 0x7E
_DEL = 0x7F
_C1_MAX = 0x9F


class OrderStatus(str, Enum):
    """予約の状態。MWL で返すのは設定の `mwl.statuses` に入れた状態だけ."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    # 始めた撮影を途中で止めた（MPPS の DISCONTINUED。PS3.3 C.4.14）。取消は撮影を始める前の取り消し
    DISCONTINUED = "discontinued"


STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.SCHEDULED: "予定",
    OrderStatus.IN_PROGRESS: "実施中",
    OrderStatus.COMPLETED: "完了",
    OrderStatus.CANCELLED: "取消",
    OrderStatus.DISCONTINUED: "中止",
}

# 状態を変更できる向き（docs/spec/01_orders.md 5 章）。完了・取消・中止は終わりの状態で、
# どこへも変更できない。同じ状態の指定は遷移ではなく「何もしない」として扱う。
# 画面・CLI の手動の変更と MPPS による変更の両方に使う
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.SCHEDULED: frozenset(
        {OrderStatus.IN_PROGRESS, OrderStatus.COMPLETED, OrderStatus.CANCELLED}
    ),
    OrderStatus.IN_PROGRESS: frozenset(
        {
            OrderStatus.SCHEDULED,
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
            OrderStatus.DISCONTINUED,
        }
    ),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.DISCONTINUED: frozenset(),
}


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    """`current` から `new` へ変更できるか。同じ状態は True（何もしない）."""
    return new == current or new in ALLOWED_TRANSITIONS[current]


def selectable_statuses(current: OrderStatus) -> list[OrderStatus]:
    """画面の選択肢：今の状態と、今の状態から変更できる状態（定義の順）."""
    return [status for status in OrderStatus if can_transition(current, status)]


def is_final(status: OrderStatus) -> bool:
    """終わりの状態（ほかの状態へ変更できない）か."""
    return not ALLOWED_TRANSITIONS[status]


# Scheduled Procedure Step Status (0040,0020) の Defined Terms（PS3.3 C.4.10）。
# 完了・取消・中止は MWL で返さない前提なので、対応する語を持たない
SPS_STATUS_TERMS: dict[OrderStatus, str] = {
    OrderStatus.SCHEDULED: "SCHEDULED",
    OrderStatus.IN_PROGRESS: "STARTED",
}


class CharacterSet(str, Enum):
    """応答の Specific Character Set の選択（docs/spec/02_mwl_scp.md 5 章）."""

    UTF8 = "utf8"
    JIS = "jis"
    JIS_KANA = "jis_kana"


# 選択 → Specific Character Set の値（値 1 の空は ISO 2022 IR 6。PS3.3 C.12.1.1.2）
CHARACTER_SET_TERMS: dict[CharacterSet, list[str]] = {
    CharacterSet.UTF8: ["ISO_IR 192"],
    CharacterSet.JIS: ["", "ISO 2022 IR 87"],
    CharacterSet.JIS_KANA: ["ISO 2022 IR 13", "ISO 2022 IR 87"],
}

# 画面・CLI・エラーの文で見せる名前（docs/spec/02_mwl_scp.md 5 章）。値を `\` でつないだ
# 文字列は日本語のフォントで `¥` に見えるので出さない。Defined Term の間は `・` でつなぐ
CHARACTER_SET_LABELS: dict[CharacterSet, str] = {
    CharacterSet.UTF8: "Unicode（UTF-8、ISO_IR 192）",
    CharacterSet.JIS: "日本語（JIS X 0208、ISO 2022 IR 87）",
    CharacterSet.JIS_KANA: "日本語と半角カナ（JIS X 0201・JIS X 0208、ISO 2022 IR 13・ISO 2022 IR 87）",
}


IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9]{1,16}")
# PS3.5 9.1：数の成分を `.` で区切る。成分は 0 か、0 で始まらない数。64 字まで
_UID_PATTERN = re.compile(r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))+")


def is_valid_uid(value: str) -> bool:
    """DICOM の UID の形か（PS3.5 9.1）."""
    return len(value) <= UI_MAX_LENGTH and _UID_PATTERN.fullmatch(value) is not None


def has_control_chars(value: str) -> bool:
    """C0・DEL・C1 の制御文字を含むか."""
    return any(ord(char) < _PRINTABLE_ASCII_MIN or _DEL <= ord(char) <= _C1_MAX for char in value)


def validate_ae_title(value: str) -> str:
    """AEタイトル：16 文字以内・空白だけは不可・表示できる ASCII で `\\` 無し（PS3.5 AE）."""
    if not value.strip():
        raise ValueError("AE title must not be empty or spaces only")
    if len(value) > AE_TITLE_MAX_LENGTH:
        raise ValueError(f"AE title must be {AE_TITLE_MAX_LENGTH} characters or fewer")
    if "\\" in value or any(
        not _PRINTABLE_ASCII_MIN <= ord(char) <= _PRINTABLE_ASCII_MAX for char in value
    ):
        raise ValueError("AE title must be printable ASCII without backslash")
    return value


class PersonName(BaseModel):
    """PN の3つのコンポーネントグループ（英字・漢字・かな）。各グループの中は `^` で姓と名を区切る."""

    model_config = {"frozen": True}

    alphabetic: str = ""
    ideographic: str = ""
    phonetic: str = ""

    @field_validator("alphabetic", "ideographic", "phonetic")
    @classmethod
    def _check_group(cls, value: str) -> str:
        """1つのコンポーネントグループは 64 字まで。`=`・`\\`・制御文字は断る（PS3.5 6.2）."""
        if len(value) > PN_GROUP_MAX_LENGTH:
            raise ValueError(
                f"name component group must be {PN_GROUP_MAX_LENGTH} characters or fewer"
            )
        if "=" in value or "\\" in value:
            raise ValueError("name component group must not contain '=' or backslash")
        if has_control_chars(value):
            raise ValueError("name component group must not contain control characters")
        return value

    def to_dicom(self) -> str:
        """`英字=漢字=かな`。後ろの空のコンポーネントグループは付けない（PS3.5 6.2.1）."""
        groups = [self.alphabetic, self.ideographic, self.phonetic]
        while groups and not groups[-1]:
            groups.pop()
        return "=".join(groups)


def validate_patient_id(value: str) -> str:
    """Patient ID：LO（64 字、`\\` と制御文字なし。PS3.5 6.2）。HL7 v2 の区切りの字
    （`^~&|`）と前後の空白も断る（HL7 v2 の PID-3 と FHIR の Identifier.value に
    エスケープなしで入れるため。docs/spec/04_identifiers.md）。統合の旧い患者ID にも使う."""
    if not value or len(value) > LO_MAX_LENGTH:
        raise ValueError(f"patient_id must be 1-{LO_MAX_LENGTH} characters")
    if "\\" in value or has_control_chars(value):
        raise ValueError("patient_id must not contain backslash or control characters")
    if any(char in HL7_V2_DELIMITERS for char in value):
        raise ValueError("patient_id must not contain HL7 v2 delimiters (^ ~ & |)")
    if value != value.strip():
        raise ValueError("patient_id must not have leading or trailing spaces")
    return value


class Patient(BaseModel):
    model_config = {"frozen": True}

    patient_id: str = Field(..., min_length=1, max_length=64)
    name: PersonName
    birth_date: str = ""  # YYYYMMDD
    sex: str = SEX_UNKNOWN  # M, F, O, U（空で渡されたら U）
    weight_kg: float | None = None
    size_m: float | None = None

    @field_validator("patient_id")
    @classmethod
    def _check_patient_id(cls, value: str) -> str:
        return validate_patient_id(value)

    @field_validator("birth_date")
    @classmethod
    def _check_birth_date(cls, value: str) -> str:
        if value and not _DATE.match(value):
            raise ValueError("birth_date must be YYYYMMDD")
        return value

    @field_validator("sex", mode="before")
    @classmethod
    def _check_sex(cls, value: str) -> str:
        if value == "":
            return SEX_UNKNOWN
        if value not in SEX_VALUES:
            raise ValueError("sex must be M, F, O or U")
        return value


class Procedure(BaseModel):
    """検査の種類（設定の `orders.modalities.<モダリティ>.procedures`）."""

    model_config = {"frozen": True}

    code: str = Field(..., min_length=1, max_length=SH_MAX_LENGTH)
    name: str = Field(..., min_length=1, max_length=LO_MAX_LENGTH)
    coding_scheme: str = Field("99RISEMU", min_length=1, max_length=SH_MAX_LENGTH)


class Order(BaseModel):
    """予約の1件。MWL の1件（Scheduled Procedure Step が1つ）に当たる."""

    accession_number: str = Field(..., min_length=1, max_length=SH_MAX_LENGTH)
    requested_procedure_id: str = Field(..., min_length=1, max_length=SH_MAX_LENGTH)
    scheduled_procedure_step_id: str = Field(..., min_length=1, max_length=SH_MAX_LENGTH)
    study_instance_uid: str = Field(..., min_length=1, max_length=UI_MAX_LENGTH)
    # Issuer of Patient ID と Issuer of Accession Number Sequence の Local Namespace
    # Entity ID（HL7 v2 の Assigning Authority の namespace ID）。空なら返さない
    issuer_namespace: str = ""
    patient: Patient
    modality: str = Field(..., min_length=1, max_length=SH_MAX_LENGTH)
    scheduled_station_ae_title: str
    scheduled_station_name: str = ""
    # 装置の台帳の名前（画面の表示用。MWL には入れない）。台帳より前に作った予約は空
    scheduled_station_label: str = ""
    scheduled_date: str  # YYYYMMDD
    scheduled_time: str  # HHMMSS
    procedure: Procedure
    requesting_service: str = Field("", max_length=LO_MAX_LENGTH)  # 依頼科
    requesting_physician: PersonName = Field(default_factory=PersonName)
    referring_physician: PersonName = Field(default_factory=PersonName)
    scheduled_performing_physician: PersonName = Field(default_factory=PersonName)
    institution_name: str = Field("", max_length=LO_MAX_LENGTH)
    priority: str = "ROUTINE"
    character_set: CharacterSet = CharacterSet.UTF8
    status: OrderStatus = OrderStatus.SCHEDULED
    # 撮り直しの予約の、元の予約の受付番号（docs/spec/01_orders.md 7 章）。MWL には入れない
    retake_of: str = ""
    created_at: str = ""
    updated_at: str = ""

    @field_validator("retake_of")
    @classmethod
    def _check_retake_of(cls, value: str) -> str:
        if value and not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("retake_of must be an accession number")
        return value

    @field_validator("scheduled_station_ae_title")
    @classmethod
    def _check_ae_title(cls, value: str) -> str:
        return validate_ae_title(value)

    @field_validator("accession_number", "requested_procedure_id", "scheduled_procedure_step_id")
    @classmethod
    def _check_sh_identifier(cls, value: str) -> str:
        """発番する SH の識別子は英数字だけ（docs/spec/04_identifiers.md の 2 章）."""
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("identifier must be ASCII letters and digits, 16 characters or fewer")
        return value

    @field_validator("study_instance_uid")
    @classmethod
    def _check_uid(cls, value: str) -> str:
        if not is_valid_uid(value):
            raise ValueError("study_instance_uid must follow PS3.5 9.1")
        return value

    @field_validator("scheduled_date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        if not _DATE.match(value):
            raise ValueError("scheduled_date must be YYYYMMDD")
        return value

    @field_validator("scheduled_time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        if not _TIME.match(value):
            raise ValueError("scheduled_time must be HHMMSS")
        return value
