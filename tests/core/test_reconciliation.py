"""MPPS の記録から照合の値を読む処理と、送る HL7 の決め方の試験（docs/spec/07_reconciliation.md 2〜3 章）."""

from __future__ import annotations

from typing import Any

import pytest
from pydicom.dataset import Dataset

from app.core.models import PersonName
from app.core.reconciliation import TemporaryPatient, plan_deliveries, read_unreconciled


def _body(**overrides: Any) -> dict[str, Any]:
    step = Dataset()
    step.StudyInstanceUID = "2.25.1"
    ds = Dataset()
    ds.ScheduledStepAttributesSequence = [step]
    ds.PatientName = "Yamada^Taro=山田^太郎=ヤマダ^タロウ"
    ds.PatientID = "ER1"
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "F"
    ds.Modality = "CT"
    ds.PerformedStationAETitle = "DTG_CT01"
    ds.PerformedStationName = "CT01"
    ds.PerformedProcedureStepStartDate = "20261021"
    ds.PerformedProcedureStepStartTime = "101530"
    for key, value in overrides.items():
        if value is None:
            del ds[key]
        else:
            setattr(ds, key, value)
    return ds.to_json_dict()


def _read(**overrides: Any):  # noqa: ANN202
    return read_unreconciled("1.2.3", "IN PROGRESS", "2026-10-21T10:15:30+09:00", _body(**overrides))


def test_reads_the_values_the_modality_sent() -> None:
    item = _read()
    assert item.problem == ""
    assert item.patient.patient_id == "ER1"
    assert item.patient.name == PersonName(
        alphabetic="Yamada^Taro", ideographic="山田^太郎", phonetic="ヤマダ^タロウ"
    )
    assert (item.patient.birth_date, item.patient.sex) == ("19800101", "F")
    assert (item.study_instance_uid, item.modality) == ("2.25.1", "CT")
    assert (item.station_ae_title, item.station_name) == ("DTG_CT01", "CT01")
    assert (item.started_date, item.started_time) == ("20261021", "101530")


def test_reads_the_first_study_uid_that_is_not_empty() -> None:
    empty, second = Dataset(), Dataset()
    empty.StudyInstanceUID = ""
    second.StudyInstanceUID = "2.25.2"
    assert _read(ScheduledStepAttributesSequence=[empty, second]).study_instance_uid == "2.25.2"


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"ScheduledStepAttributesSequence": []}, "Study Instance UID"),
        ({"PatientID": ""}, "仮の患者 ID がありません"),
        ({"PatientID": "A|B"}, "HL7 に入れられません"),
        ({"PatientName": "A" * 70}, "氏名を読めません"),
    ],
)
def test_problems_are_reported(overrides: dict[str, Any], problem: str) -> None:
    assert problem in _read(**overrides).problem


def test_unreadable_values_become_empty() -> None:
    item = _read(
        PatientSex="X",
        PatientBirthDate="19",
        PerformedStationAETitle="a\\b",
        PerformedProcedureStepStartDate=None,
        PerformedProcedureStepStartTime="9:15",
        PatientName=None,
    )
    assert item.patient.sex == "" and item.patient.birth_date == ""
    assert item.station_ae_title == "" and item.started_date == "" and item.started_time == ""
    assert item.patient.name == PersonName()


def test_missing_modality_is_empty() -> None:
    assert _read(Modality=None).modality == ""


def test_plan_deliveries() -> None:
    name = PersonName(alphabetic="A^B")
    temporary = TemporaryPatient("ER1", name, "19800101", "F")
    assert plan_deliveries(temporary, "P1", name, "19800101", "F") == ["a40", "orm"]
    assert plan_deliveries(temporary, "ER1", PersonName(alphabetic="C^D"), "19800101", "F") == ["a08", "orm"]
    assert plan_deliveries(temporary, "ER1", name, "19900101", "F") == ["a08", "orm"]
    assert plan_deliveries(temporary, "ER1", name, "19800101", "M") == ["a08", "orm"]
    assert plan_deliveries(temporary, "ER1", name, "19800101", "F") == ["orm"]
