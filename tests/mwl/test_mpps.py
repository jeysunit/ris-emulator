"""MPPS の SCP を立て、pynetdicom の SCU から N-CREATE・N-SET を送る試験（docs/spec/05_mpps_scp.md）."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE, Association, evt
from pynetdicom.sop_class import ModalityPerformedProcedureStep

from app.core.models import Order, OrderStatus
from app.mwl.mpps import handle_n_create, handle_n_set
from app.mwl.server import MwlServer, find_worklist
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore

from tests.conftest import TODAY

SCU_AE = "TEST_MOD"


@pytest.fixture
def server(config: AppConfig, store: OrderStore) -> Iterator[MwlServer]:
    mwl = MwlServer(config.mwl, store)
    mwl.start()
    yield mwl
    mwl.stop()


@pytest.fixture
def assoc(server: MwlServer) -> Iterator[Association]:
    ae = AE(ae_title=SCU_AE)
    ae.add_requested_context(ModalityPerformedProcedureStep)
    association = ae.associate("127.0.0.1", server.port, ae_title="RIS_EMU")
    assert association.is_established
    yield association
    association.release()


def _orders(service: OrderService, count: int = 1) -> list[Order]:
    return service.create_orders(OrderRequest(counts={"CT": count}, scheduled_date=TODAY, seed=1))


def _step(order: Order | None, accession: str = "", step_id: str = "") -> Dataset:
    item = Dataset()
    item.StudyInstanceUID = order.study_instance_uid if order else generate_uid()
    item.ReferencedStudySequence = []
    item.AccessionNumber = order.accession_number if order else accession
    item.RequestedProcedureID = order.requested_procedure_id if order else ""
    item.RequestedProcedureDescription = ""
    item.ScheduledProcedureStepID = order.scheduled_procedure_step_id if order else step_id
    item.ScheduledProcedureStepDescription = ""
    item.ScheduledProtocolCodeSequence = []
    return item


def _create_attributes(*steps: Dataset, status: str = "IN PROGRESS") -> Dataset:
    """PS3.4 Table F.7.2-1 の N-CREATE の属性のうち、試験に要るもの."""
    ds = Dataset()
    ds.SpecificCharacterSet = "ISO_IR 192"
    ds.ScheduledStepAttributesSequence = list(steps)
    ds.PatientName = "TEST^PATIENT"
    ds.PatientID = "P1"
    ds.PerformedProcedureStepID = "PPS1"
    ds.PerformedStationAETitle = SCU_AE
    ds.PerformedStationName = ""
    ds.PerformedLocation = ""
    ds.PerformedProcedureStepStartDate = "20261021"
    ds.PerformedProcedureStepStartTime = "100000"
    ds.PerformedProcedureStepStatus = status
    ds.Modality = "CT"
    ds.StudyID = ""
    ds.PerformedProtocolCodeSequence = []
    ds.PerformedSeriesSequence = []
    return ds


def _set_attributes(status: str | None) -> Dataset:
    ds = Dataset()
    if status is not None:
        ds.PerformedProcedureStepStatus = status
    ds.PerformedProcedureStepEndDate = "20261021"
    ds.PerformedProcedureStepEndTime = "101500"
    return ds


def _create(assoc: Association, uid: str, attributes: Dataset) -> int:
    status, _ = assoc.send_n_create(attributes, ModalityPerformedProcedureStep, uid)
    return int(status.Status)


def _set(assoc: Association, uid: str, status: str | None) -> Dataset:
    result, _ = assoc.send_n_set(_set_attributes(status), ModalityPerformedProcedureStep, uid)
    return result


def test_n_create_moves_order_to_in_progress(
    assoc: Association, service: OrderService
) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    assert _create(assoc, uid, _create_attributes(_step(order))) == 0x0000
    assert service.get(order.accession_number).status is OrderStatus.IN_PROGRESS
    records = service.list_mpps(order.accession_number)
    assert [(r.sop_instance_uid, r.status) for r in records] == [(uid, "IN PROGRESS")]


def test_group_case_links_every_order(assoc: Association, service: OrderService) -> None:
    first, second = _orders(service, 2)
    assert _create(assoc, generate_uid(), _create_attributes(_step(first), _step(second))) == 0
    assert service.get(first.accession_number).status is OrderStatus.IN_PROGRESS
    assert service.get(second.accession_number).status is OrderStatus.IN_PROGRESS


def test_unscheduled_mpps_is_recorded_only(assoc: Association, service: OrderService) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    assert _create(assoc, uid, _create_attributes(_step(None))) == 0x0000
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED
    # 記録はある（どの予約にも結び付かない）ので、続く N-SET も受け付ける
    assert int(_set(assoc, uid, "COMPLETED").Status) == 0x0000


def test_both_identifiers_must_match(assoc: Association, service: OrderService) -> None:
    order = _orders(service)[0]
    step = _step(None, accession=order.accession_number, step_id="SPS_OTHER")
    assert _create(assoc, generate_uid(), _create_attributes(step)) == 0x0000
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED


def test_n_create_must_be_in_progress(assoc: Association, service: OrderService) -> None:
    order = _orders(service)[0]
    attributes = _create_attributes(_step(order), status="COMPLETED")
    assert _create(assoc, generate_uid(), attributes) == 0x0106
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED
    assert service.list_mpps(order.accession_number) == []


def test_duplicate_sop_instance(assoc: Association, service: OrderService) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    assert _create(assoc, uid, _create_attributes(_step(order))) == 0x0000
    assert _create(assoc, uid, _create_attributes(_step(order))) == 0x0111


def test_final_order_is_not_changed_by_mpps(assoc: Association, service: OrderService) -> None:
    order = _orders(service)[0]
    service.set_status(order.accession_number, OrderStatus.CANCELLED)
    uid = generate_uid()
    assert _create(assoc, uid, _create_attributes(_step(order))) == 0x0000
    assert service.get(order.accession_number).status is OrderStatus.CANCELLED
    assert len(service.list_mpps(order.accession_number)) == 1


@pytest.mark.parametrize(
    ("pps_status", "order_status"),
    [("COMPLETED", OrderStatus.COMPLETED), ("DISCONTINUED", OrderStatus.DISCONTINUED)],
)
def test_n_set_completes_or_discontinues(
    assoc: Association, service: OrderService, pps_status: str, order_status: OrderStatus
) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    assert _create(assoc, uid, _create_attributes(_step(order))) == 0x0000
    assert int(_set(assoc, uid, None).Status) == 0x0000
    assert service.get(order.accession_number).status is OrderStatus.IN_PROGRESS
    assert int(_set(assoc, uid, pps_status).Status) == 0x0000
    assert service.get(order.accession_number).status is order_status
    assert service.list_mpps(order.accession_number)[0].status == pps_status


def test_n_set_after_final_state_fails(assoc: Association, service: OrderService) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    _create(assoc, uid, _create_attributes(_step(order)))
    _set(assoc, uid, "COMPLETED")
    result = _set(assoc, uid, "DISCONTINUED")
    assert int(result.Status) == 0x0110
    assert int(result.ErrorID) == 0xA710
    assert service.get(order.accession_number).status is OrderStatus.COMPLETED
    assert service.list_mpps(order.accession_number)[0].status == "COMPLETED"


def test_n_set_unknown_instance(assoc: Association) -> None:
    assert int(_set(assoc, generate_uid(), "COMPLETED").Status) == 0x0112


def test_completed_order_leaves_worklist(
    assoc: Association, service: OrderService, store: OrderStore, config: AppConfig
) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    _create(assoc, uid, _create_attributes(_step(order)))
    _set(assoc, uid, "COMPLETED")
    query = Dataset()
    query.AccessionNumber = order.accession_number
    status, responses = find_worklist(query, store, config.mwl)
    assert status == 0x0000 and responses == []


def test_scp_assigns_uid_when_missing(store: OrderStore, service: OrderService) -> None:
    """PS3.7 10.1.5.1.4：要求に SOP Instance UID が無ければ SCP が発番して応答で返す."""
    order = _orders(service)[0]
    status, reply = handle_n_create(store, None, _create_attributes(_step(order)))
    assert status == 0x0000 and reply is not None
    uid = str(reply.AffectedSOPInstanceUID)
    assert uid.startswith("2.25.")
    assert service.list_mpps(order.accession_number)[0].sop_instance_uid == uid


def test_assigned_uid_is_in_the_response_command(server: MwlServer, service: OrderService) -> None:
    """SOP Instance UID を付けない N-CREATE の応答の Command Set に、発番した UID が入る."""
    order = _orders(service)[0]
    received: list[str] = []

    def on_recv(event: evt.Event) -> None:
        command = event.message.command_set
        if "AffectedSOPInstanceUID" in command:
            received.append(str(command.AffectedSOPInstanceUID))

    ae = AE(ae_title=SCU_AE)
    ae.add_requested_context(ModalityPerformedProcedureStep)
    association = ae.associate(
        "127.0.0.1", server.port, ae_title="RIS_EMU", evt_handlers=[(evt.EVT_DIMSE_RECV, on_recv)]
    )
    assert association.is_established
    try:
        status, _ = association.send_n_create(
            _create_attributes(_step(order)), ModalityPerformedProcedureStep, None
        )
        assert int(status.Status) == 0x0000
        assert len(received) == 1 and received[0].startswith("2.25.")
        # 受け取った UID で N-SET できる
        result, _ = association.send_n_set(
            _set_attributes("COMPLETED"), ModalityPerformedProcedureStep, received[0]
        )
        assert int(result.Status) == 0x0000
    finally:
        association.release()
    assert service.get(order.accession_number).status is OrderStatus.COMPLETED


@pytest.mark.parametrize("uid", ["1.2.abc", "1.02.3", "1." + "2" * 70])
def test_invalid_uid_is_refused(store: OrderStore, service: OrderService, uid: str) -> None:
    order = _orders(service)[0]
    status, _ = handle_n_create(store, uid, _create_attributes(_step(order)))
    assert status == 0x0106
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED


def test_unknown_status_in_n_set_is_refused(store: OrderStore, service: OrderService) -> None:
    order = _orders(service)[0]
    uid = generate_uid()
    handle_n_create(store, uid, _create_attributes(_step(order)))
    status, _ = handle_n_set(store, uid, _set_attributes("DONE"))
    assert status == 0x0106
    assert service.list_mpps(order.accession_number)[0].status == "IN PROGRESS"


def test_missing_attributes_are_refused(store: OrderStore) -> None:
    no_status = _create_attributes(_step(None))
    del no_status.PerformedProcedureStepStatus
    assert handle_n_create(store, generate_uid(), no_status)[0] == 0x0120
    no_steps = _create_attributes()
    del no_steps.ScheduledStepAttributesSequence
    assert handle_n_create(store, generate_uid(), no_steps)[0] == 0x0120


def test_unexpected_error_returns_processing_failure(
    assoc: Association, server: MwlServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(server.store, "create_mpps", boom)
    assert _create(assoc, generate_uid(), _create_attributes(_step(None))) == 0x0110
    # SCP は止まらず、次の要求を受ける
    assert int(_set(assoc, generate_uid(), "COMPLETED").Status) == 0x0112
