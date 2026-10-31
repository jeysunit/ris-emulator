"""応答の Identifier の組み立てと文字コードの試験."""

from __future__ import annotations

import pytest
from pydicom.dataset import Dataset
from pydicom.filebase import DicomBytesIO
from pydicom.filereader import read_dataset
from pydicom.filewriter import write_dataset

from app.core.models import (
    CHARACTER_SET_LABELS,
    CHARACTER_SET_TERMS,
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


@pytest.mark.parametrize(("sex", "written"), [("M", "M"), ("F", "F"), ("O", "O"), ("U", ""), ("", "")])
def test_patient_sex_unknown_is_written_empty(sex: str, written: str) -> None:
    # Patient's Sex の列挙値は M・F・O だけ。U（不明）と空は、空で書く
    order = _order()
    patient = order.patient.model_copy(update={"sex": sex})
    assert order_to_dataset(order.model_copy(update={"patient": patient})).PatientSex == written


def test_patient_sex_is_u_when_empty_or_missing() -> None:
    name = PersonName(alphabetic="TANAKA^HIROSHI")
    assert Patient(patient_id="P1", name=name).sex == "U"
    assert Patient(patient_id="P1", name=name, sex="").sex == "U"
    with pytest.raises(ValueError, match="sex"):
        Patient(patient_id="P1", name=name, sex="X")


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


def test_character_set_labels() -> None:
    """選択肢はすべて名前を持ち、名前に値の区切り `\\` も、それが見える `¥` も無い."""
    assert set(CHARACTER_SET_LABELS) == set(CharacterSet)
    for label in CHARACTER_SET_LABELS.values():
        assert "\\" not in label and "¥" not in label
    assert CHARACTER_SET_LABELS[CharacterSet.JIS] == "日本語（JIS X 0208、ISO 2022 IR 87）"


@pytest.mark.parametrize("choice", list(CharacterSet))
def test_character_set_terms_follow_ps3_3(choice: CharacterSet) -> None:
    """PS3.3 C.12.1.1.2：ISO_IR 192 は値1つだけ。符号拡張（ISO 2022）は値2つ以上で、重ねない."""
    terms = CHARACTER_SET_TERMS[choice]
    if "ISO_IR 192" in terms:
        assert terms == ["ISO_IR 192"]
    if any(term.startswith("ISO 2022") for term in terms):
        assert len(terms) >= 2
        # 値 1 の空は ISO 2022 IR 6 とみなす
        effective = [term or "ISO 2022 IR 6" for term in terms]
        assert len(set(effective)) == len(effective)
        assert all(term.startswith("ISO 2022") for term in effective)


def _bytes(text: str) -> bytes:
    """PS3.5 の Encoded representation（`05/09` のような 列/行 の並び）をバイト列にする."""
    return bytes(int(column) * 16 + int(row) for column, row in (pair.split("/") for pair in text.split()))


def test_jis_encoding_matches_ps3_5_example_h3_1() -> None:
    """PS3.5 Example H.3-1（Specific Character Set `\\ISO 2022 IR 87`）と同じバイト列になる."""
    name = PersonName(alphabetic="Yamada^Tarou", ideographic="山田^太郎", phonetic="やまだ^たろう")
    patient = _order().patient.model_copy(update={"name": name})
    ds = order_to_dataset(_order(character_set=CharacterSet.JIS, patient=patient))
    buffer = DicomBytesIO()
    buffer.is_little_endian = True
    buffer.is_implicit_VR = True
    write_dataset(buffer, ds)
    expected = _bytes(
        "05/09 06/01 06/13 06/01 06/04 06/01 5/14 05/04 06/01 07/02 06/15 07/05 03/13 "
        "01/11 02/04 04/02 03/11 03/03 04/05 04/04 01/11 02/08 04/02 05/14 "
        "01/11 02/04 04/02 04/02 04/00 04/15 03/10 01/11 02/08 04/02 03/13 "
        "01/11 02/04 04/02 02/04 06/04 02/04 05/14 02/04 04/00 01/11 02/08 04/02 05/14 "
        "01/11 02/04 04/02 02/04 03/15 02/04 06/13 02/04 02/06 01/11 02/08 04/02"
    )
    assert expected in buffer.getvalue()
