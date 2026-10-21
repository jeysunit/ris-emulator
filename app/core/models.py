"""予約（Order）と患者のモデル（spec/01_orders.md）."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

AE_TITLE_MAX_LENGTH = 16
SH_MAX_LENGTH = 16
LO_MAX_LENGTH = 64
PN_GROUP_MAX_LENGTH = 64
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


STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.SCHEDULED: "予定",
    OrderStatus.IN_PROGRESS: "実施中",
    OrderStatus.COMPLETED: "完了",
    OrderStatus.CANCELLED: "取消",
}

# Scheduled Procedure Step Status (0040,0020) の Defined Terms（PS3.3 C.4.10）。
# 完了・取消は MWL で返さない前提なので、対応する語を持たない
SPS_STATUS_TERMS: dict[OrderStatus, str] = {
    OrderStatus.SCHEDULED: "SCHEDULED",
    OrderStatus.IN_PROGRESS: "STARTED",
}


class CharacterSet(str, Enum):
    """応答の Specific Character Set の選択（dicom-test-generator の spec/12 7.1 と同じ3つ）."""

    UTF8 = "utf8"
    JIS = "jis"
    JIS_KANA = "jis_kana"


# 選択 → Specific Character Set の値（値 1 の空は ISO 2022 IR 6。PS3.3 C.12.1.1.2）
CHARACTER_SET_TERMS: dict[CharacterSet, list[str]] = {
    CharacterSet.UTF8: ["ISO_IR 192"],
    CharacterSet.JIS: ["", "ISO 2022 IR 87"],
    CharacterSet.JIS_KANA: ["ISO 2022 IR 13", "ISO 2022 IR 87"],
}


def has_control_chars(value: str) -> bool:
    """C0・DEL・C1 の制御文字を含むか."""
    return any(ord(char) < _PRINTABLE_ASCII_MIN or _DEL <= ord(char) <= _C1_MAX for char in value)


def validate_ae_title(value: str) -> str:
    """AE タイトル：16 文字以内・空白だけは不可・表示できる ASCII で `\\` 無し（PS3.5 AE）."""
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


class Patient(BaseModel):
    model_config = {"frozen": True}

    patient_id: str = Field(..., min_length=1, max_length=64)
    name: PersonName
    birth_date: str = ""  # YYYYMMDD
    sex: str = ""  # M, F, O, 空
    weight_kg: float | None = None
    size_m: float | None = None

    @field_validator("birth_date")
    @classmethod
    def _check_birth_date(cls, value: str) -> str:
        if value and not _DATE.match(value):
            raise ValueError("birth_date must be YYYYMMDD")
        return value

    @field_validator("sex")
    @classmethod
    def _check_sex(cls, value: str) -> str:
        if value not in ("", "M", "F", "O"):
            raise ValueError("sex must be M, F, O or empty")
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
    study_instance_uid: str = Field(..., min_length=1, max_length=64)
    patient: Patient
    modality: str = Field(..., min_length=1, max_length=SH_MAX_LENGTH)
    scheduled_station_ae_title: str
    scheduled_station_name: str = ""
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
    created_at: str = ""
    updated_at: str = ""

    @field_validator("scheduled_station_ae_title")
    @classmethod
    def _check_ae_title(cls, value: str) -> str:
        return validate_ae_title(value)

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
