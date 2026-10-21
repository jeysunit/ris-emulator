"""照合（PS3.4 C.2.2.2）の試験."""

from __future__ import annotations

from pydicom.dataset import Dataset

from app.core.matching import has_matching_keys, matches, person_name_matches, wildcard_matches


def _full() -> Dataset:
    ds = Dataset()
    ds.PatientName = "TANAKA^HIROSHI=田中^博=タナカ^ヒロシ"
    ds.PatientID = "P000001"
    ds.AccessionNumber = "RE202610210001"
    ds.StudyInstanceUID = "2.25.1234"
    sps = Dataset()
    sps.ScheduledStationAETitle = "DTG_CT01"
    sps.ScheduledProcedureStepStartDate = "20261021"
    sps.ScheduledProcedureStepStartTime = "093000"
    sps.Modality = "CT"
    code = Dataset()
    code.CodeValue = "CT0002"
    sps.ScheduledProtocolCodeSequence = [code]
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def _request(**sps_values: str) -> Dataset:
    ds = Dataset()
    ds.PatientName = ""
    ds.PatientID = ""
    sps = Dataset()
    sps.ScheduledStationAETitle = ""
    sps.ScheduledProcedureStepStartDate = ""
    sps.ScheduledProcedureStepStartTime = ""
    sps.Modality = ""
    for keyword, value in sps_values.items():
        setattr(sps, keyword, value)
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def test_universal_matching_matches_everything() -> None:
    assert matches(_full(), _request())


def test_empty_identifier_has_no_matching_keys() -> None:
    ds = Dataset()
    ds.SpecificCharacterSet = "ISO_IR 192"
    assert not has_matching_keys(ds)
    assert has_matching_keys(_request())


def test_station_ae_title_single_value() -> None:
    assert matches(_full(), _request(ScheduledStationAETitle="DTG_CT01"))
    assert not matches(_full(), _request(ScheduledStationAETitle="DTG_MR01"))


def test_modality_single_value() -> None:
    assert matches(_full(), _request(Modality="CT"))
    assert not matches(_full(), _request(Modality="MR"))


def test_date_single_and_range() -> None:
    assert matches(_full(), _request(ScheduledProcedureStepStartDate="20261021"))
    assert matches(_full(), _request(ScheduledProcedureStepStartDate="20261021-20261021"))
    assert matches(_full(), _request(ScheduledProcedureStepStartDate="20261020-"))
    assert matches(_full(), _request(ScheduledProcedureStepStartDate="-20261021"))
    assert not matches(_full(), _request(ScheduledProcedureStepStartDate="20261022-20261023"))
    assert not matches(_full(), _request(ScheduledProcedureStepStartDate="20261020"))


def test_time_range_alone() -> None:
    assert matches(_full(), _request(ScheduledProcedureStepStartTime="0900-1000"))
    assert matches(_full(), _request(ScheduledProcedureStepStartTime="09-09"))
    assert not matches(_full(), _request(ScheduledProcedureStepStartTime="1000-1200"))


def test_date_and_time_ranges_make_one_period() -> None:
    """日付 10/20〜10/22 と時刻 10:00〜18:00 は 10/20 10:00 から 10/22 18:00 まで（K.6-1）."""
    request = _request(
        ScheduledProcedureStepStartDate="20261020-20261022",
        ScheduledProcedureStepStartTime="1000-1800",
    )
    # 10/21 09:30 は期間の中（時刻だけで見れば範囲の外）
    assert matches(_full(), request)
    early = _request(
        ScheduledProcedureStepStartDate="20261021-20261022",
        ScheduledProcedureStepStartTime="1000-1800",
    )
    assert not matches(_full(), early)


def test_patient_id_single_value() -> None:
    request = _request()
    request.PatientID = "P000001"
    assert matches(_full(), request)
    request.PatientID = "P00000"
    assert not matches(_full(), request)


def test_accession_wildcard() -> None:
    request = _request()
    request.AccessionNumber = "RE2026*"
    assert matches(_full(), request)
    request.AccessionNumber = "RE2025*"
    assert not matches(_full(), request)


def test_uid_list_matching() -> None:
    request = _request()
    request.StudyInstanceUID = ["2.25.1", "2.25.1234"]
    assert matches(_full(), request)
    request.StudyInstanceUID = "2.25.1"
    assert not matches(_full(), request)


def test_sequence_matching_inside_nested_code_sequence() -> None:
    request = _request()
    code = Dataset()
    code.CodeValue = "CT0002"
    request.ScheduledProcedureStepSequence[0].ScheduledProtocolCodeSequence = [code]
    assert matches(_full(), request)
    code.CodeValue = "CT0009"
    assert not matches(_full(), request)


def test_unsupported_key_is_ignored_for_matching() -> None:
    request = _request()
    request.AdmissionID = "ADM1"
    assert matches(_full(), request)


def test_person_name_each_group_and_case() -> None:
    value = "TANAKA^HIROSHI=田中^博=タナカ^ヒロシ"
    assert person_name_matches("tanaka*", value)
    assert person_name_matches("TANAKA*^HIROSHI*", value)
    assert person_name_matches("田中*", value)
    assert person_name_matches("田中*^博*", value)
    assert person_name_matches("タナカ*", value)
    assert person_name_matches("=田中^博", value)
    assert not person_name_matches("=佐藤*", value)
    assert not person_name_matches("SATO*", value)


def test_wildcard_question_mark() -> None:
    assert wildcard_matches("P00000?", "P000001", ignore_case=False)
    assert not wildcard_matches("P0000?", "P000001", ignore_case=False)
    assert wildcard_matches("*", "", ignore_case=False)
    assert wildcard_matches("a*b*c", "aXXbYYc", ignore_case=False)
    assert not wildcard_matches("a*b*c", "aXXbYY", ignore_case=False)
    assert wildcard_matches("*?", "x", ignore_case=False)
    assert not wildcard_matches("*?", "", ignore_case=False)


def test_wildcard_does_not_blow_up() -> None:
    """`*?` の繰り返しと無い字の組でも、すぐに終わる（正規表現の後戻りにしない）."""
    import time

    started = time.monotonic()
    assert not wildcard_matches("*?" * 200 + "Z", "A" * 400, ignore_case=True)
    assert time.monotonic() - started < 2.0


def test_time_fraction_is_compared() -> None:
    assert not matches(_full(), _request(ScheduledProcedureStepStartTime="093000.5-"))
    assert matches(_full(), _request(ScheduledProcedureStepStartTime="-093000.5"))
    assert matches(_full(), _request(ScheduledProcedureStepStartTime="093000"))
