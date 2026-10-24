"""照合の独立レビューで出た点の試験：複数値の属性、同時の送信、MPPS の更新との競合、表示の安全."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset

from app.cli.main import main
from app.core.models import Patient, PersonName
from app.services.config import AppConfig
from app.services.order_service import OrderService
from app.services.reconciliation import ReconcileRequest, ReconciliationService
from app.services.store import OrderStore
from app.web.app import create_app
from tests.conftest import NOW, ROOT, TODAY, add_unscheduled_mpps
from tests.hl7.stub import ack, stub_receiver

OFFICIAL = Patient(
    patient_id="P000001", name=PersonName(alphabetic="TANAKA^HIROSHI"), birth_date="", sex="M"
)
ORIGIN = "http://127.0.0.1:8081"


def _service(config: AppConfig, store: OrderStore, port: int) -> ReconciliationService:
    hl7 = config.hl7.model_copy(update={"port": port, "timeout_seconds": 2.0})
    orders = OrderService(
        config.model_copy(update={"hl7": hl7}), store, today=lambda: TODAY, now=lambda: NOW
    )
    return ReconciliationService(orders)


def _set_mpps(store: OrderStore, sop_uid: str, **values: str) -> None:
    """MPPS の記録の属性を、N-SET と同じ形で書き換える."""
    changes = Dataset()
    for key, value in values.items():
        setattr(changes, key, value)
    store.update_mpps(sop_uid, None, changes.to_json_dict())


def test_multi_valued_patient_name_does_not_break_the_list(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store, name="A\\B")
    items = _service(config, store, 1).list_unreconciled()
    assert [i.sop_instance_uid for i in items] == [sop_uid]
    assert items[0].patient.name == PersonName()


def test_a_delivery_is_not_sent_while_another_sender_holds_it(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    started, release = threading.Event(), threading.Event()

    def slow(text: str) -> bytes:
        started.set()
        release.wait(5)
        return ack("AA", text)

    with stub_receiver(slow) as receiver:
        service = _service(config, store, receiver.port)
        # 照合のあとの送信が終わる前に、同じ通をもう一度送ろうとする
        outcome: dict[str, object] = {}
        worker = threading.Thread(
            target=lambda: outcome.setdefault("result", service.reconcile(ReconcileRequest(sop_uid, OFFICIAL)))
        )
        worker.start()
        assert started.wait(5)
        listed = store.get_reconciliation(_only_accession(store))
        assert listed is not None
        second = service.send_pending(listed.accession_number)
        assert [d.attempts for d in second.deliveries] == [1, 0]
        release.set()
        worker.join(10)
    assert len(receiver.types) == 2 and receiver.types[0] == "ADT^A40"
    final = store.get_reconciliation(_only_accession(store))
    assert final is not None and [d.outcome for d in final.deliveries] == ["accepted", "accepted"]
    assert [d.attempts for d in final.deliveries] == [1, 1]


def _only_accession(store: OrderStore) -> str:
    return store.list_orders()[0].accession_number


def test_claim_expires_so_a_crashed_sender_does_not_block_forever(store: OrderStore, config: AppConfig) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(lambda text: ack("AE", text)) as receiver:
        result = _service(config, store, receiver.port).reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    accession = result.accession_number
    assert store.claim_delivery(accession, 0, now=1000.0, lease_seconds=30) is not None
    assert store.claim_delivery(accession, 0, now=1010.0, lease_seconds=30) is None
    again = store.claim_delivery(accession, 0, now=1031.0, lease_seconds=30)
    assert again is not None and again.attempts == 3


def test_patient_changed_by_n_set_before_commit_is_used_for_the_hl7(
    config: AppConfig, store: OrderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(lambda text: ack("AA", text)) as receiver:
        service = _service(config, store, receiver.port)
        real = service.store.reconcile_mpps

        def racing(counter, uid, build):  # noqa: ANN001, ANN202
            _set_mpps(store, sop_uid, PatientID="ER9")
            return real(counter, uid, build)

        monkeypatch.setattr(service.store, "reconcile_mpps", racing)
        result = service.reconcile(ReconcileRequest(sop_uid, OFFICIAL))
    assert result.temporary["patient_id"] == "ER9"
    assert "\rMRG|ER9^^^RIS_EMU^PI|" in receiver.received[0]


def test_department_outside_the_config_is_refused_in_the_web(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    service = _service(config, store, 1).orders
    app = create_app(service.config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            f"/reconciliation/{sop_uid}",
            data={
                "csrf_token": app.state.csrf_token,
                "patient": "roster",
                "roster_patient_id": "P000001",
                "department": "存在しない科",
            },
            headers={"Origin": ORIGIN},
        )
    assert response.status_code == 400 and "依頼科を選び直してください" in response.text
    assert service.count_orders() == 0


def test_html_is_escaped_in_the_list_and_the_resend_needs_csrf(config: AppConfig, store: OrderStore) -> None:
    add_unscheduled_mpps(store, name="<script>alert(1)</script>^X", patient_id="ER1")
    service = _service(config, store, 1).orders
    app = create_app(service.config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        page = client.get("/reconciliation").text
        resend = client.post("/orders/RE000/hl7/resend", headers={"Origin": ORIGIN})
    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert resend.status_code == 403


def test_cli_list_makes_control_characters_visible(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = yaml.safe_load((ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8"))
    raw["database"] = str(tmp_path / "ris.sqlite3")
    config_file = tmp_path / "app_config.yaml"
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    add_unscheduled_mpps(OrderStore(tmp_path / "ris.sqlite3"), patient_id="ER\x1b[2J1")
    assert main(["reconcile", "list", "--config", str(config_file)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\\u001b" in out and "照合できません" in out
