"""MWL の SCP を立て、pynetdicom の SCU で C-FIND を引く試験."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification

from app.core.models import CharacterSet, OrderStatus
from app.mwl.server import MwlServer, find_worklist
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore

from tests.conftest import TODAY, new_order_service

SCU_AE = "TEST_SCU"


@pytest.fixture
def server(config: AppConfig, store: OrderStore) -> Iterator[MwlServer]:
    mwl = MwlServer(config.mwl, store)
    mwl.start()
    yield mwl
    mwl.stop()


def _find(server: MwlServer, identifier: Dataset, called: str = "RIS_EMU") -> tuple[list[Dataset], int]:
    ae = AE(ae_title=SCU_AE)
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = ae.associate("127.0.0.1", server.port, ae_title=called)
    assert assoc.is_established
    found: list[Dataset] = []
    final = -1
    try:
        for status, response in assoc.send_c_find(identifier, ModalityWorklistInformationFind):
            assert status, "no response"
            code = int(status.Status)
            if code in (0xFF00, 0xFF01):
                found.append(response)
            else:
                final = code
    finally:
        assoc.release()
    return found, final


def _query(**sps_values: str) -> Dataset:
    """モダリティの問い合わせによくある形（Return Key を空で並べる）."""
    ds = Dataset()
    for keyword in (
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientSex",
        "PatientWeight",
        "PatientSize",
        "StudyInstanceUID",
        "AccessionNumber",
        "RequestingPhysician",
        "ReferringPhysicianName",
        "RequestedProcedureID",
        "RequestedProcedureDescription",
        "InstitutionName",
    ):
        setattr(ds, keyword, "")
    ds.RequestedProcedureCodeSequence = []
    sps = Dataset()
    for keyword in (
        "ScheduledStationAETitle",
        "ScheduledProcedureStepStartDate",
        "ScheduledProcedureStepStartTime",
        "Modality",
        "ScheduledPerformingPhysicianName",
        "ScheduledProcedureStepID",
        "ScheduledProcedureStepDescription",
    ):
        setattr(sps, keyword, "")
    sps.ScheduledProtocolCodeSequence = []
    for keyword, value in sps_values.items():
        setattr(sps, keyword, value)
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def _seed(service: OrderService) -> list:
    orders = service.create_orders(
        OrderRequest(counts={"CT": 3, "MR": 1}, scheduled_date=TODAY, seed=3)
    )
    tomorrow = service.create_orders(
        OrderRequest(counts={"CT": 1}, scheduled_date=TODAY.replace(day=22), seed=4)
    )
    return orders + tomorrow


def test_filter_by_station_and_date_range(server: MwlServer, service: OrderService) -> None:
    orders = _seed(service)
    found, final = _find(
        server,
        _query(ScheduledStationAETitle="CT01", ScheduledProcedureStepStartDate="20261021-20261021"),
    )
    assert final == 0x0000
    assert sorted(r.AccessionNumber for r in found) == sorted(o.accession_number for o in orders[:3])
    response = found[0]
    order = next(o for o in orders if o.accession_number == response.AccessionNumber)
    assert response.SpecificCharacterSet == "ISO_IR 192"
    assert str(response.PatientName) == order.patient.name.to_dicom()
    assert response.PatientID == order.patient.patient_id
    assert response.StudyInstanceUID == order.study_instance_uid
    assert response.RequestedProcedureID == order.requested_procedure_id
    assert response.InstitutionName == "TEST HOSPITAL"
    assert response.RequestedProcedureCodeSequence[0].CodeValue == order.procedure.code
    sps = response.ScheduledProcedureStepSequence[0]
    assert sps.Modality == "CT"
    assert sps.ScheduledStationAETitle == "CT01"
    assert sps.ScheduledProcedureStepID == order.scheduled_procedure_step_id
    assert sps.ScheduledProtocolCodeSequence[0].CodeValue == order.procedure.code
    # 要求に無い属性は返さない
    assert "RequestingService" not in response
    assert "ScheduledProcedureStepStatus" not in sps


def test_retake_order_is_returned_with_new_study(
    server: MwlServer, config: AppConfig, store: OrderStore
) -> None:
    retaking = new_order_service(config, store)
    original = retaking.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    retaking.set_status(original.accession_number, OrderStatus.IN_PROGRESS)
    retake, _ = retaking.create_retake(original.accession_number)
    found, final = _find(
        server, _query(ScheduledStationAETitle="CT01", ScheduledProcedureStepStartDate="20261021")
    )
    assert final == 0x0000
    # 元の予約は中止になって返らず、撮り直しの予約が新しい Study Instance UID で返る
    assert [r.AccessionNumber for r in found] == [retake.accession_number]
    assert found[0].StudyInstanceUID == retake.study_instance_uid != original.study_instance_uid


def test_filter_by_modality_and_open_range(server: MwlServer, service: OrderService) -> None:
    _seed(service)
    found, _ = _find(server, _query(Modality="CT", ScheduledProcedureStepStartDate="20261021-"))
    assert len(found) == 4
    found, _ = _find(server, _query(Modality="MR"))
    assert len(found) == 1


def test_filter_by_patient_id_and_japanese_name(server: MwlServer, service: OrderService) -> None:
    orders = _seed(service)
    target = orders[1].patient
    query = _query()
    query.PatientID = target.patient_id
    found, _ = _find(server, query)
    assert [r.PatientID for r in found] == [target.patient_id]

    family = target.name.ideographic.split("^")[0]
    query = _query()
    query.SpecificCharacterSet = "ISO_IR 192"
    query.PatientName = f"{family}*"
    found, _ = _find(server, query)
    assert target.patient_id in {r.PatientID for r in found}
    assert all(str(r.PatientName).split("=")[1].startswith(family) for r in found)


def test_completed_and_cancelled_are_not_returned(server: MwlServer, service: OrderService) -> None:
    orders = _seed(service)
    service.set_status(orders[0].accession_number, OrderStatus.COMPLETED)
    service.set_status(orders[1].accession_number, OrderStatus.CANCELLED)
    service.set_status(orders[2].accession_number, OrderStatus.IN_PROGRESS)
    query = _query(Modality="CT", ScheduledProcedureStepStartDate="20261021")
    query.ScheduledProcedureStepSequence[0].ScheduledProcedureStepStatus = ""
    found, _ = _find(server, query)
    assert [r.AccessionNumber for r in found] == [orders[2].accession_number]
    assert found[0].ScheduledProcedureStepSequence[0].ScheduledProcedureStepStatus == "STARTED"


def test_jis_character_sets_over_the_network(server: MwlServer, service: OrderService) -> None:
    for choice, expected in (
        (CharacterSet.JIS, ["", "ISO 2022 IR 87"]),
        (CharacterSet.JIS_KANA, ["ISO 2022 IR 13", "ISO 2022 IR 87"]),
    ):
        orders = service.create_orders(
            OrderRequest(counts={"US": 1}, scheduled_date=TODAY, character_set=choice, seed=9)
        )
        query = _query()
        query.AccessionNumber = orders[0].accession_number
        found, _ = _find(server, query)
        assert len(found) == 1
        assert list(found[0].SpecificCharacterSet) == expected
        assert str(found[0].PatientName) == orders[0].patient.name.to_dicom()
        assert found[0].RequestedProcedureDescription == orders[0].procedure.name


def test_unsupported_keys_make_pending_warning(
    config: AppConfig, store: OrderStore, service: OrderService
) -> None:
    """持っている属性だけの要求は FF00、この SCP が持たない属性があれば FF01（PS3.4 Table K.4-1）."""
    _seed(service)
    status, responses = find_worklist(_query(Modality="MR"), store, config.mwl)
    assert status == 0x0000 and [pending for pending, _ in responses] == [0xFF00]
    query = _query(Modality="MR")
    query.PatientComments = ""
    _, responses = find_worklist(query, store, config.mwl)
    assert [pending for pending, _ in responses] == [0xFF01]
    assert "PatientComments" in responses[0][1]


def test_identifier_without_keys_returns_nothing(
    config: AppConfig, store: OrderStore, service: OrderService
) -> None:
    """照合の属性が1つも無い要求は一致なし（PS3.4 K.4.1.3.1）。空の Identifier は送れないので関数で確かめる."""
    _seed(service)
    request = Dataset()
    request.SpecificCharacterSet = "ISO_IR 192"
    assert find_worklist(request, store, config.mwl) == (0x0000, [])


def test_max_results_refuses(config: AppConfig, store: OrderStore, service: OrderService) -> None:
    _seed(service)
    mwl = MwlServer(config.mwl.model_copy(update={"max_results": 2}), store)
    mwl.start()
    try:
        found, final = _find(mwl, _query())
    finally:
        mwl.stop()
    assert found == [] and final == 0xA700


def test_wrong_called_ae_title_is_rejected(server: MwlServer) -> None:
    ae = AE(ae_title=SCU_AE)
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = ae.associate("127.0.0.1", server.port, ae_title="OTHER")
    assert assoc.is_rejected


def test_c_echo(server: MwlServer) -> None:
    ae = AE(ae_title=SCU_AE)
    ae.add_requested_context(Verification)
    assoc = ae.associate("127.0.0.1", server.port, ae_title="RIS_EMU")
    assert assoc.is_established
    try:
        assert int(assoc.send_c_echo().Status) == 0x0000
    finally:
        assoc.release()
