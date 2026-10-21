"""応答の Identifier の組み立てと文字コードの試験."""

from __future__ import annotations

import pytest
from pydicom.dataset import Dataset
from pydicom.filebase import DicomBytesIO
from pydicom.filereader import read_dataset
from pydicom.filewriter import write_dataset

from app.core.models import (
    CharacterSet,
    Order,
    OrderStatus,
    Patient,
    PersonName,
    Procedure,
)
from app.core.mwl_dataset import build_response, order_to_dataset


def _order(**updates: object) -> Order:
    order = Order(
        accession_number="RE202610210001",
        requested_procedure_id="RP202610210001",
        scheduled_procedure_step_id="SPS202610210001",
        study_instance_uid="2.25.1234",
        patient=Patient(
            patient_id="P000001",
            name=PersonName(alphabetic="TANAKA^HIROSHI", ideographic="田中^博", phonetic="タナカ^ヒロシ"),
            birth_date="19980312",
            sex="M",
            weight_kg=58.5,
            size_m=1.72,
        ),
        modality="CT",
        scheduled_station_ae_title="CT01",
        scheduled_station_name="CT_ROOM_1",
        scheduled_date="20261021",
        scheduled_time="093000",
        procedure=Procedure(code="CT0002", name="胸部 CT 単純"),
        requesting_service="内科",
        requesting_physician=PersonName(alphabetic="SATO^YUKI", ideographic="佐藤^由紀", phonetic="サトウ^ユキ"),
        referring_physician=PersonName(alphabetic="SATO^YUKI", ideographic="佐藤^由紀", phonetic="サトウ^ユキ"),
        institution_name="TEST HOSPITAL",
    )
    return order.model_copy(update=updates)


def test_full_dataset_has_ihe_required_values() -> None:
    ds = order_to_dataset(_order())
    assert ds.SpecificCharacterSet == "ISO_IR 192"
    assert str(ds.PatientName) == "TANAKA^HIROSHI=田中^博=タナカ^ヒロシ"
    assert ds.PatientID == "P000001"
    assert ds.PatientBirthDate == "19980312"
    assert ds.PatientSex == "M"
    assert ds.PatientWeight == "58.5"
    assert ds.PatientSize == "1.72"
    assert ds.AccessionNumber == "RE202610210001"
    assert ds.RequestedProcedureID == "RP202610210001"
    assert ds.RequestedProcedureDescription == "胸部 CT 単純"
    assert ds.RequestedProcedureCodeSequence[0].CodeValue == "CT0002"
    assert ds.StudyInstanceUID == "2.25.1234"
    assert ds.RequestingService == "内科"
    sps = ds.ScheduledProcedureStepSequence[0]
    assert sps.ScheduledStationAETitle == "CT01"
    assert sps.ScheduledStationName == "CT_ROOM_1"
    assert sps.ScheduledProcedureStepStartDate == "20261021"
    assert sps.ScheduledProcedureStepStartTime == "093000"
    assert sps.Modality == "CT"
    assert sps.ScheduledProcedureStepID == "SPS202610210001"
    assert sps.ScheduledProcedureStepDescription == "胸部 CT 単純"
    assert sps.ScheduledProtocolCodeSequence[0].CodeMeaning == "胸部 CT 単純"
    assert sps.ScheduledProcedureStepStatus == "SCHEDULED"


def test_in_progress_status_term() -> None:
    sps = order_to_dataset(_order(status=OrderStatus.IN_PROGRESS)).ScheduledProcedureStepSequence[0]
    assert sps.ScheduledProcedureStepStatus == "STARTED"


def test_response_has_only_requested_keys() -> None:
    request = Dataset()
    request.PatientName = ""
    request.PatientID = ""
    request.AdmissionID = ""
    request.PatientComments = ""  # この SCP が持たない属性
    sps = Dataset()
    sps.Modality = ""
    sps.ScheduledProcedureStepStartDate = "20261021"
    request.ScheduledProcedureStepSequence = [sps]
    response = build_response(order_to_dataset(_order()), request)
    keywords = {element.keyword for element in response}
    assert keywords == {
        "SpecificCharacterSet",
        "PatientName",
        "PatientID",
        "AdmissionID",
        "PatientComments",
        "ScheduledProcedureStepSequence",
    }
    assert response.PatientComments in (None, "")
    item = response.ScheduledProcedureStepSequence[0]
    assert {element.keyword for element in item} == {"Modality", "ScheduledProcedureStepStartDate"}


def test_empty_sequence_in_request_returns_whole_item() -> None:
    request = Dataset()
    request.ScheduledProcedureStepSequence = []
    request.RequestedProcedureCodeSequence = []
    request.IssuerOfAccessionNumberSequence = []
    response = build_response(order_to_dataset(_order()), request)
    item = response.ScheduledProcedureStepSequence[0]
    assert item.ScheduledStationAETitle == "CT01"
    assert item.ScheduledProtocolCodeSequence[0].CodeValue == "CT0002"
    assert response.RequestedProcedureCodeSequence[0].CodingSchemeDesignator == "99RISEMU"
    assert len(response.IssuerOfAccessionNumberSequence) == 0


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (CharacterSet.UTF8, "ISO_IR 192"),
        (CharacterSet.JIS, ["", "ISO 2022 IR 87"]),
        (CharacterSet.JIS_KANA, ["ISO 2022 IR 13", "ISO 2022 IR 87"]),
    ],
)
def test_character_sets_round_trip(choice: CharacterSet, expected: object) -> None:
    """3つの文字コードで書いて読み戻し、氏名と日本語の値が元に戻る."""
    ds = order_to_dataset(_order(character_set=choice))
    value = ds.SpecificCharacterSet
    assert (value if isinstance(value, str) else list(value)) == expected
    buffer = DicomBytesIO()
    buffer.is_little_endian = True
    buffer.is_implicit_VR = True
    write_dataset(buffer, ds)
    buffer.seek(0)
    restored = read_dataset(buffer, is_implicit_VR=True, is_little_endian=True)
    restored.decode()
    assert str(restored.PatientName) == "TANAKA^HIROSHI=田中^博=タナカ^ヒロシ"
    assert restored.RequestedProcedureDescription == "胸部 CT 単純"
    assert restored.RequestingService == "内科"
    raw = buffer.getvalue()
    if choice is CharacterSet.UTF8:
        assert "田中".encode() in raw
    else:
        assert b"\x1b$B" in raw  # JIS X 0208 への切り替え
