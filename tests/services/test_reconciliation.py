"""照合の試験（docs/spec/07_reconciliation.md）。受け手は試験用のスタブ."""

from __future__ import annotations

import socket

import pytest

from app.core.exceptions import AlreadyReconciledError, MppsNotFoundError, ValidationError
from app.core.models import OrderStatus, Patient, PersonName
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.reconciliation import ReconcileRequest, ReconciliationService
from app.services.store import OrderStore
from tests.conftest import NOW, TODAY, add_unscheduled_mpps
from tests.hl7.stub import ack, stub_receiver

OFFICIAL = Patient(
    patient_id="P000001",
    name=PersonName(
        alphabetic="TANAKA^HIROSHI", ideographic="田中^博", phonetic="タナカ^ヒロシ"
    ),
    birth_date="19980312",
    sex="M",
)


def _service(config: AppConfig, store: OrderStore, port: int) -> ReconciliationService:
    hl7 = config.hl7.model_copy(update={"port": port, "timeout_seconds": 2.0})
    orders = OrderService(
        config.model_copy(update={"hl7": hl7}), store, today=lambda: TODAY, now=lambda: NOW
    )
    return ReconciliationService(orders)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _accept_all(text: str) -> bytes:
    return ack("AA", text)


def _outcomes(reconciliation) -> list[tuple[str, str]]:  # noqa: ANN001
    return [(d.message_type, d.outcome) for d in reconciliation.deliveries]


def test_only_unlinked_mpps_are_listed(config: AppConfig, store: OrderStore) -> None:
    orders = OrderService(config, store, today=lambda: TODAY)
    scheduled = orders.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    store.create_mpps("1.2.3", [(scheduled.accession_number, scheduled.scheduled_procedure_step_id)], {})
    sop_uid, _ = add_unscheduled_mpps(store)
    service = ReconciliationService(orders)
    listed = service.list_unreconciled()
    assert [item.sop_instance_uid for item in listed] == [sop_uid]
    item = listed[0]
    assert item.patient.patient_id == "ER2026102400"
    assert item.patient.name.ideographic == "不明^男性"
    assert (item.modality, item.station_ae_title) == ("CT", "DTG_CT01")
    assert (item.started_date, item.started_time) == ("20261021", "101530")
    assert item.problem == ""


def test_reconcile_with_new_patient_id_sends_a40_then_orm(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert receiver.types == ["ADT^A40", "ORM^O01"]
    assert _outcomes(result) == [("ADT^A40", "accepted"), ("ORM^O01", "accepted")]
    order = store.get(result.accession_number)
    # 撮影が持つ Study Instance UID をそのまま使い、MPPS の状態に合わせて実施中になる
    assert order.study_instance_uid == study_uid
    assert order.status is OrderStatus.IN_PROGRESS
    assert order.patient == OFFICIAL
    assert (order.scheduled_date, order.scheduled_time) == ("20261021", "101530")
    assert order.accession_number.startswith("RE20261021")
    a40, orm = receiver.received
    assert "\rMRG|ER2026102400^^^RIS_EMU^PI|" in a40
    assert "PID|1||P000001^^^RIS_EMU^PI||TANAKA^HIROSHI^^^^^L^A" in a40
    assert f"ZDS|{study_uid}^RIS_EMU^Application^DICOM" in orm
    assert f"\rPV1|1|E|" in orm and "\rORC|NW|" in orm
    # MPPS は予約に結び付き、未照合の一覧から外れる
    assert store.get_mpps(sop_uid).accession_numbers == [order.accession_number]
    assert service.list_unreconciled() == []
    assert result.temporary["patient_id"] == "ER2026102400"


def test_completed_mpps_makes_a_completed_order(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store, status="COMPLETED")
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert store.get(result.accession_number).status is OrderStatus.COMPLETED


def test_mpps_set_after_reconcile_reaches_the_order(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    store.update_mpps(sop_uid, "COMPLETED", {})
    assert store.get(result.accession_number).status is OrderStatus.COMPLETED


@pytest.mark.parametrize(
    ("official", "expected"),
    [
        # 患者ID が同じで氏名が違う：属性の更新
        (OFFICIAL.model_copy(update={"patient_id": "ER2026102400"}), ["ADT^A08", "ORM^O01"]),
        # 患者ID も氏名・生年月日・性別も同じ：予約の知らせだけ
        (
            Patient(
                patient_id="ER2026102400",
                name=PersonName(
                    alphabetic="UNKNOWN^MALE", ideographic="不明^男性", phonetic="フメイ^ダンセイ"
                ),
                sex="M",
            ),
            ["ORM^O01"],
        ),
    ],
)
def test_same_patient_id_sends_a08_or_only_orm(
    config: AppConfig, store: OrderStore, official: Patient, expected: list[str]
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, official))
    assert receiver.types == expected
    assert all(d.outcome == "accepted" for d in result.deliveries)


def test_rejected_a40_stops_before_orm_and_resend_sends_the_same_message(
    config: AppConfig, store: OrderStore
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    answers = iter(["AE", "AA", "AA"])
    with stub_receiver(lambda text: ack(next(answers), text, "patient is unknown")) as receiver:
        service = _service(config, store, receiver.port)
        first = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
        # 拒否されても照合は残り、ORM は送らない
        assert _outcomes(first) == [("ADT^A40", "rejected"), ("ORM^O01", "pending")]
        assert (first.deliveries[0].ack_code, first.deliveries[0].detail) == ("AE", "patient is unknown")
        assert receiver.types == ["ADT^A40"]
        assert store.get(first.accession_number).patient == OFFICIAL
        second = service.send_pending(first.accession_number)
    assert _outcomes(second) == [("ADT^A40", "accepted"), ("ORM^O01", "accepted")]
    assert second.deliveries[0].attempts == 2 and second.deliveries[1].attempts == 1
    # 送り直しは同じ本文（同じ MSH-10）
    assert receiver.received[0] == receiver.received[1]
    assert second.deliveries[0].control_id == first.deliveries[0].control_id


def test_accepted_messages_are_not_sent_again(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
        service.send_pending(result.accession_number)
    assert len(receiver.received) == 2


def test_unreachable_receiver_keeps_the_reconciliation(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    service = _service(config, store, _free_port())
    result = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert _outcomes(result) == [("ADT^A40", "failed"), ("ORM^O01", "pending")]
    assert result.deliveries[0].detail and result.deliveries[0].sent_at
    assert store.get(result.accession_number).status is OrderStatus.IN_PROGRESS


def test_ack_text_is_made_visible(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(lambda text: ack("AE", text, "bad\x1b[31m")) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert "\x1b" not in result.deliveries[0].detail and "\\u001b" in result.deliveries[0].detail


def test_already_reconciled_is_refused_and_nothing_changes(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        first = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
        before = service.orders.count_orders()
        with pytest.raises(AlreadyReconciledError) as raised:
            service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert raised.value.details["accession_number"] == first.accession_number
    assert service.orders.count_orders() == before == 1
    assert len(receiver.received) == 2


def test_scheduled_mpps_cannot_be_reconciled(config: AppConfig, store: OrderStore) -> None:
    orders = OrderService(config, store, today=lambda: TODAY)
    order = orders.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    store.create_mpps("1.2.3", [(order.accession_number, order.scheduled_procedure_step_id)], {})
    with pytest.raises(AlreadyReconciledError):
        ReconciliationService(orders).reconcile(ReconcileRequest("1.2.3", OFFICIAL))


def test_unknown_mpps(config: AppConfig, store: OrderStore) -> None:
    with pytest.raises(MppsNotFoundError):
        _service(config, store, 1).reconcile(ReconcileRequest("9.9.9", OFFICIAL))


def test_modality_not_in_config_is_refused(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store, modality="XA")
    service = _service(config, store, _free_port())
    with pytest.raises(ValidationError, match="XA"):
        service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert service.orders.count_orders() == 0 and len(service.list_unreconciled()) == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"patient_id": ""}, "仮の患者ID"),
        ({"patient_id": "ER^1"}, "仮の患者ID"),
    ],
)
def test_mpps_that_cannot_be_reconciled_says_why(
    config: AppConfig, store: OrderStore, overrides: dict[str, str], message: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store, **overrides)
    service = _service(config, store, _free_port())
    assert message in service.list_unreconciled()[0].problem
    with pytest.raises(ValidationError, match=message):
        service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert service.orders.count_orders() == 0


def test_bad_message_input_rolls_everything_back(config: AppConfig, store: OrderStore) -> None:
    """HL7 に入れられない値（氏名が空）は、予約も連番も残さない."""
    sop_uid, _ = add_unscheduled_mpps(store)
    nameless = OFFICIAL.model_copy(update={"name": PersonName()})
    service = _service(config, store, _free_port())
    with pytest.raises(ValidationError):
        service.reconcile(ReconcileRequest(sop_uid, nameless))
    assert service.orders.count_orders() == 0
    assert store.get_mpps(sop_uid).accession_numbers == []
    # 連番を使っていない：次の照合の受付番号は 0001
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert result.accession_number == "RE202610210001"


def test_empty_issuer_namespace_is_refused(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    orders = config.orders.model_copy(update={"issuer_namespace": ""})
    service = _service(config.model_copy(update={"orders": orders}), store, _free_port())
    with pytest.raises(ValidationError, match="issuer_namespace"):
        service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert service.orders.count_orders() == 0


def test_procedure_and_department_choices(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        with pytest.raises(ValidationError, match="CT9999"):
            service.reconcile(ReconcileRequest(sop_uid, OFFICIAL, procedure_code="CT9999"))
        result = service.reconcile(
            ReconcileRequest(sop_uid, OFFICIAL, procedure_code="CT0002", department="外科")
        )
    order = store.get(result.accession_number)
    assert (order.procedure.code, order.requesting_service) == ("CT0002", "外科")


def test_default_procedure_and_department(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    order = store.get(result.accession_number)
    assert (order.procedure.code, order.requesting_service, order.priority) == ("CT0001", "救急科", "STAT")
    # 台帳に無い AEタイトルは、撮影が名乗った値のまま持つ（装置の名前は付かない）
    assert (order.scheduled_station_label, order.scheduled_station_ae_title) == ("", "DTG_CT01")


def test_station_in_the_registry_gets_its_name(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store, station_ae_title="CT01")
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    order = store.get(result.accession_number)
    assert (order.scheduled_station_label, order.scheduled_station_ae_title) == ("CT1号機", "CT01")


@pytest.mark.parametrize("patient_id,linked", [("ER2026102400", True), ("P000001", True), ("OTHER", False)])
@pytest.mark.parametrize("status", ["IN PROGRESS", "COMPLETED"])
def test_later_mpps_joins_reconciled_study(config, store, patient_id, linked, status):
    sop_uid, study_uid = add_unscheduled_mpps(store, status=status)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    later, _ = add_unscheduled_mpps(store, study_instance_uid=study_uid, patient_id=patient_id)
    assert store.get_mpps(later).accession_numbers == ([result.accession_number] if linked else [])
    assert len(store.list_mpps(result.accession_number)) == (2 if linked else 1)
    assert [m.sop_instance_uid for m in store.list_unlinked_mpps()] == ([] if linked else [later])
    expected = OrderStatus.COMPLETED if status == "COMPLETED" else OrderStatus.IN_PROGRESS
    assert store.get(result.accession_number).status == expected


def test_study_uid_does_not_join_an_ordinary_order(config, store):
    orders = OrderService(config, store, today=lambda: TODAY)
    order = orders.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY))[0]
    uid, _ = add_unscheduled_mpps(store, study_instance_uid=order.study_instance_uid,
                                  patient_id=order.patient.patient_id)
    assert store.get_mpps(uid).accession_numbers == []
    result = store.create_mpps("1.2.99", [(order.accession_number, order.scheduled_procedure_step_id, "1.2.3")], {}, "OTHER")
    assert result.linked == [order.accession_number]


def test_study_uid_is_not_used_when_accession_is_given(config, store):
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    # 受付番号が入っていて一致しない項目は、照合済みの Study UID でも結ばない
    linked = store.create_mpps("1.2.98", [("RE0000000000", "SPS0", study_uid)], {}, "ER2026102400")
    assert linked.linked == []
    assert len(store.list_mpps(result.accession_number)) == 1


@pytest.mark.parametrize("status,control", [(OrderStatus.CANCELLED, "CA"), (OrderStatus.DISCONTINUED, "DC")])
def test_manual_status_sends_rad13_and_same_status_does_nothing(config, store, status, control):
    uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(uid, OFFICIAL))
        order, updated = service.set_status(result.accession_number, status)
        assert order.status == status
        assert updated.deliveries[-1].kind == "orm_" + control.lower()
        assert updated.deliveries[-1].outcome == "accepted"
        assert f"\rORC|{control}|" in receiver.received[-1]
        assert service.set_status(order.accession_number, status)[1] is None
    assert len(receiver.received) == 3


def test_rejected_nw_blocks_ca_until_resend(config, store):
    uid, _ = add_unscheduled_mpps(store)
    answers = iter(["AA", "AE", "AE", "AA", "AA"])
    with stub_receiver(lambda text: ack(next(answers), text)) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(uid, OFFICIAL))
        _, updated = service.set_status(result.accession_number, OrderStatus.CANCELLED)
        assert [d.outcome for d in updated.deliveries] == ["accepted", "rejected", "pending"]
        final = service.send_pending(result.accession_number)
    controls = [line.split("|")[1] for text in receiver.received for line in text.split("\r") if line.startswith("ORC|")]
    assert controls == ["NW", "NW", "NW", "CA"]
    assert all(d.outcome == "accepted" for d in final.deliveries)


def test_mpps_discontinued_does_not_add_delivery(config, store):
    uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(uid, OFFICIAL))
    store.update_mpps(uid, "DISCONTINUED", {})
    assert len(store.get_reconciliation(result.accession_number).deliveries) == 2
    assert store.get(result.accession_number).status == OrderStatus.DISCONTINUED


def test_ordinary_order_status_does_not_send(config, store):
    orders = OrderService(config, store, today=lambda: TODAY)
    order = orders.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY))[0]
    def unexpected(*args):
        raise AssertionError("送信してはいけない")
    service = ReconciliationService(orders, send=unexpected)
    changed, result = service.set_status(order.accession_number, OrderStatus.CANCELLED)
    assert changed.status == OrderStatus.CANCELLED and result is None


def test_status_delivery_failure_rolls_back(config, store, monkeypatch):
    uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept_all) as receiver:
        service = _service(config, store, receiver.port)
        result = service.reconcile(ReconcileRequest(uid, OFFICIAL))
    before = store.get(result.accession_number)
    def broken(*args):
        raise RuntimeError("組み立て失敗")
    monkeypatch.setattr(service, "_build_delivery", broken)
    with pytest.raises(RuntimeError):
        service.set_status(result.accession_number, OrderStatus.CANCELLED)
    assert store.get(result.accession_number) == before
    assert store.get_reconciliation(result.accession_number) == result
