"""未照合の MPPS の読み取りと、照合の組み立て（docs/spec/07_reconciliation.md）.

ファイル・通信・ログを使わない。MPPS の記録（pydicom の JSON の形）から、仮の患者と
Study Instance UID などを取り出し、正式な患者と予約を結ぶときに送る HL7 の種類を決める。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

from app.core.models import OrderStatus, PersonName, validate_ae_title, validate_patient_id

# orm は ORC-1 が NW。orm_ca・orm_dc は、照合で作った予約を取消・中止したときの RAD-13
DeliveryKind = Literal["a40", "a08", "orm", "orm_ca", "orm_dc"]
MESSAGE_TYPES: dict[DeliveryKind, str] = {
    "a40": "ADT^A40",
    "a08": "ADT^A08",
    "orm": "ORM^O01",
    "orm_ca": "ORM^O01（CA）",
    "orm_dc": "ORM^O01（DC）",
}
# 予約の状態 → 照合で作った予約を手で変えたときに送る通
STATUS_DELIVERIES: dict[OrderStatus, DeliveryKind] = {
    OrderStatus.CANCELLED: "orm_ca",
    OrderStatus.DISCONTINUED: "orm_dc",
}
ORDER_CONTROLS: dict[DeliveryKind, str] = {"orm": "NW", "orm_ca": "CA", "orm_dc": "DC"}
# 送信の状態の画面・CLI での名前（docs/spec/07_reconciliation.md 5 章）
DELIVERY_LABELS = {
    "pending": "送信待ち",
    "accepted": "送信完了",
    "rejected": "拒否",
    "failed": "送信失敗",
}
_DATE = re.compile(r"\d{8}")
_TIME = re.compile(r"\d{6}")


@dataclass(frozen=True)
class TemporaryPatient:
    """予約の無い撮影で、モダリティが入力した仮の患者（MPPS の患者の属性）."""

    patient_id: str = ""
    name: PersonName = PersonName()
    birth_date: str = ""
    sex: str = ""


@dataclass(frozen=True)
class UnreconciledMpps:
    """予約に結び付かなかった MPPS から読み取った値。`problem` が空でなければ照合できない."""

    sop_instance_uid: str
    status: str
    received_at: str
    patient: TemporaryPatient
    study_instance_uid: str
    modality: str
    station_ae_title: str
    station_name: str
    started_date: str  # YYYYMMDD、読めなければ空
    started_time: str  # HHMMSS、読めなければ空
    problem: str = ""


def read_unreconciled(
    sop_instance_uid: str, status: str, received_at: str, body: dict[str, Any]
) -> UnreconciledMpps:
    """MPPS の記録（N-CREATE と N-SET の属性を重ねた JSON）を読む."""
    dataset = Dataset.from_json(body)
    study_uid = _study_instance_uid(dataset)
    patient_id = _text(dataset, "PatientID")
    problem = ""
    if not study_uid:
        problem = "MPPS に Study Instance UID がありません"
    elif not patient_id:
        problem = "MPPS に仮の患者ID がありません"
    else:
        try:
            validate_patient_id(patient_id)
        except ValueError:
            problem = "仮の患者ID を HL7 に入れられません"
    try:
        name = _person_name(dataset)
    except ValueError:
        name = PersonName()
        problem = problem or "MPPS の氏名を読めません"
    return UnreconciledMpps(
        sop_instance_uid=sop_instance_uid,
        status=status,
        received_at=received_at,
        patient=TemporaryPatient(
            patient_id=patient_id,
            name=name,
            birth_date=_digits(_text(dataset, "PatientBirthDate"), _DATE, 8),
            sex=_sex(_text(dataset, "PatientSex")),
        ),
        study_instance_uid=study_uid,
        modality=_text(dataset, "Modality"),
        station_ae_title=_ae_title(_text(dataset, "PerformedStationAETitle")),
        station_name=_text(dataset, "PerformedStationName")[:16],
        started_date=_digits(_text(dataset, "PerformedProcedureStepStartDate"), _DATE, 8),
        started_time=_digits(_text(dataset, "PerformedProcedureStepStartTime"), _TIME, 6),
        problem=problem,
    )


def plan_deliveries(
    temporary: TemporaryPatient, official_id: str, official_name: PersonName, birth_date: str, sex: str
) -> list[DeliveryKind]:
    """送る HL7 の種類を順に返す（docs/spec/07_reconciliation.md 3 章）.

    患者ID が違えば A40、同じで氏名・生年月日・性別が違えば A08、すべて同じなら送らない。
    どの場合も最後に、予約を知らせる ORM（NW）を送る。
    """
    if temporary.patient_id != official_id:
        return ["a40", "orm"]
    changed = (
        temporary.name.to_dicom() != official_name.to_dicom()
        or temporary.birth_date != birth_date
        or temporary.sex != sex
    )
    return ["a08", "orm"] if changed else ["orm"]


def _study_instance_uid(dataset: Dataset) -> str:
    for item in dataset.get("ScheduledStepAttributesSequence", None) or []:
        uid = _text(item, "StudyInstanceUID")
        if uid:
            return uid
    return ""


def _text(dataset: Dataset, keyword: str) -> str:
    """属性の値の文字列。無い・複数の値（`\\` で区切られた）なら空."""
    value = dataset.get(keyword, None)
    if value is None or isinstance(value, MultiValue):
        return ""
    return str(value).strip()


def _person_name(dataset: Dataset) -> PersonName:
    value = dataset.get("PatientName", None)
    if value is None or isinstance(value, MultiValue) or not str(value):
        return PersonName()
    # pydicom の PersonName は、グループ内の `^` をそのまま持つ
    return PersonName(
        alphabetic=str(value.components[0]) if len(value.components) > 0 else "",
        ideographic=str(value.components[1]) if len(value.components) > 1 else "",
        phonetic=str(value.components[2]) if len(value.components) > 2 else "",  # noqa: PLR2004
    )


def _digits(value: str, pattern: re.Pattern[str], length: int) -> str:
    """`YYYYMMDD`・`HHMMSS` の先頭を取る（小数の秒などは捨てる）。形が合わなければ空."""
    head = value[:length]
    return head if pattern.fullmatch(head) else ""


def _sex(value: str) -> str:
    return value if value in ("M", "F", "O") else ""


def _ae_title(value: str) -> str:
    try:
        return validate_ae_title(value)
    except ValueError:
        return ""
