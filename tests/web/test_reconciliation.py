"""照合の画面の試験（docs/spec/07_reconciliation.md 5 章）。HL7 の受け手は試験用のスタブ."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore
from app.web.app import create_app
from tests.conftest import NOW, TODAY, add_unscheduled_mpps
from tests.hl7.stub import ack, stub_receiver

ORIGIN = "http://127.0.0.1:8081"
ROSTER_ID = "P000001"


@contextmanager
def _client(
    config: AppConfig, store: OrderStore, port: int = 1
) -> Iterator[tuple[TestClient, OrderService]]:
    hl7 = config.hl7.model_copy(update={"port": port, "timeout_seconds": 2.0})
    service = OrderService(
        config.model_copy(update={"hl7": hl7}), store, today=lambda: TODAY, now=lambda: NOW
    )
    app = create_app(service.config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, service


def _post(client: TestClient, path: str, **data: str):  # noqa: ANN202
    return client.post(
        path,
        data={"csrf_token": client.app.state.csrf_token, **data},  # type: ignore[attr-defined]
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )


def _roster(**extra: str) -> dict[str, str]:
    return {"patient": "roster", "roster_patient_id": ROSTER_ID, **extra}


def _accept(text: str) -> bytes:
    return ack("AA", text)


def test_empty_list(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, _):
        page = client.get("/reconciliation")
    assert page.status_code == 200
    assert "<h1>未照合</h1>" in page.text and "未照合の撮影はありません。" in page.text
    assert "<title>未照合 - ris-emulator</title>" in page.text


def test_list_shows_unreconciled_only_and_links_to_the_form(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        scheduled = service.create_orders(
            OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1)
        )[0]
        store.create_mpps("1.2.3", [(scheduled.accession_number, scheduled.scheduled_procedure_step_id)], {})
        page = client.get("/reconciliation").text
    assert "ER2026102400" in page and study_uid in page and "不明 男性" in page
    assert page.count("<tbody>") == 1 and page.count("<tr>") == 2  # 見出しと1件
    assert f'href="/reconciliation/{sop_uid}"' in page
    headers = [h.strip() for h in re.findall(r"<th[^>]*>(?:<span[^>]*>)?([^<]*)", page) if h.strip()]
    assert headers == [
        "受けた日時", "状態", "患者ID", "氏名", "生年月日・性別",
        "モダリティ", "予定の AEタイトル", "Study Instance UID", "操作",
    ]  # fmt: skip


def test_form_shows_the_shooting_and_choices(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        page = client.get(f"/reconciliation/{sop_uid}").text
    assert study_uid in page and "UNKNOWN^MALE=不明^男性=フメイ^ダンセイ" in page
    assert f'<option value="{ROSTER_ID}"' in page
    assert re.findall(r'<option value="(CT\d{4})"', page) == ["CT0001", "CT0002", "CT0003", "CT0004"]
    assert '<option value="救急科" selected>' in page
    assert "照合・送信</button>" in page
    assert f'action="/reconciliation/{sop_uid}"' in page


def test_unknown_mpps_is_404(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, _):
        assert client.get("/reconciliation/9.9.9").status_code == 404
        assert _post(client, "/reconciliation/9.9.9", **_roster()).status_code == 404
        assert _post(client, "/orders/RE000/hl7/resend").status_code == 404


def test_form_says_why_it_cannot_reconcile(config: AppConfig, store: OrderStore) -> None:
    no_id, _ = add_unscheduled_mpps(store, patient_id="")
    unknown_modality, _ = add_unscheduled_mpps(store, modality="XA")
    with _client(config, store) as (client, _):
        first = client.get(f"/reconciliation/{no_id}").text
        second = client.get(f"/reconciliation/{unknown_modality}").text
    assert "仮の患者ID がありません" in first and "<form" not in first
    assert "モダリティ XA が設定に無い" in second and "<form" not in second


def test_reconcile_with_roster_patient_sends_and_shows_the_result(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        response = _post(
            client, f"/reconciliation/{sop_uid}", **_roster(procedure="CT0002", department="外科")
        )
        assert response.status_code == 303
        location = response.headers["location"]
        detail = client.get(location).text
        listing = client.get("/reconciliation").text
    assert receiver.types == ["ADT^A40", "ORM^O01"]
    accession = location.rsplit("/", 1)[1]
    order = service.get(accession)
    assert order.study_instance_uid == study_uid and order.patient.patient_id == ROSTER_ID
    assert (order.procedure.code, order.requesting_service) == ("CT0002", "外科")
    assert "<h2>HL7 送信</h2>" in detail
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", detail) == ["送信完了", "送信完了"]
    assert "<dt>照合前の患者ID</dt><dd class=\"mono\">ER2026102400</dd>" in detail
    assert "UNKNOWN^MALE=不明^男性=フメイ^ダンセイ" in detail
    assert "再送信" not in detail
    assert "未照合の撮影はありません。" in listing


def test_reconcile_with_typed_patient(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id="X0001",
            alphabetic_family="SATO",
            alphabetic_given="JIRO",
            ideographic_family="佐藤",
            ideographic_given="次郎",
            phonetic_family="",
            phonetic_given="",
            birth_date="1975-04-05",
            sex="M",
            procedure="CT0001",
            department="救急科",
        )
        assert response.status_code == 303
        order = service.get(response.headers["location"].rsplit("/", 1)[1])
    patient = order.patient
    assert (patient.patient_id, patient.birth_date, patient.sex) == ("X0001", "19750405", "M")
    assert patient.name.to_dicom() == "SATO^JIRO=佐藤^次郎"
    assert "PID|1||X0001^^^RIS_EMU^PI||SATO^JIRO^^^^^L^A~佐藤^次郎^^^^^L^I" in receiver.received[0]


def test_input_errors_are_shown_and_nothing_is_created(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    cases = [
        ({}, "患者を、名簿から選ぶか入力するかを選んでください"),
        ({"patient": "roster", "roster_patient_id": ""}, "名簿の患者を選んでください"),
        ({"patient": "roster", "roster_patient_id": "NOPE"}, "名簿に無い患者ID です"),
        ({"patient": "manual", "patient_id": ""}, "患者ID を入力してください"),
        ({"patient": "manual", "patient_id": "X1"}, "氏名を入力してください"),
        (
            {"patient": "manual", "patient_id": "X1", "alphabetic_family": "A", "birth_date": "1975-13-45"},
            "生年月日",
        ),
        (
            {"patient": "manual", "patient_id": "X^1", "alphabetic_family": "A"},
            "患者の値が正しくありません",
        ),
        (_roster(procedure="CT9999"), "CT9999"),
    ]
    with _client(config, store) as (client, service):
        for data, message in cases:
            response = _post(client, f"/reconciliation/{sop_uid}", **data)
            assert response.status_code == 400, (data, response.text[:200])
            assert message in response.text, data
            assert 'role="alert"' in response.text
        assert service.count_orders() == 0
        assert len(service.store.list_unlinked_mpps()) == 1


def test_values_are_kept_when_the_form_is_shown_again(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id="X0001",
            alphabetic_family="SATO",
            birth_date="1975-13-45",
            department="外科",
        )
    page = response.text
    assert response.status_code == 400
    assert 'value="X0001"' in page and 'value="SATO"' in page and 'value="1975-13-45"' in page
    assert '<option value="外科" selected>' in page


def test_second_reconcile_is_refused(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        accession = _post(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        again = _post(client, f"/reconciliation/{sop_uid}", **_roster())
        page = client.get(f"/reconciliation/{sop_uid}")
        assert service.count_orders() == 1
    assert again.status_code == 409 and "すでに予約に結び付いています" in again.text
    assert f'<a href="{accession}"' in again.text and "<form" not in again.text
    assert "<form" not in page.text and f'<a href="{accession}"' in page.text
    assert len(receiver.received) == 2


def test_rejected_message_is_shown_and_can_be_sent_again(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    answers = iter(["AE", "AA", "AA"])
    with stub_receiver(lambda text: ack(next(answers), text, "unknown patient")) as receiver, _client(
        config, store, receiver.port
    ) as (client, _):
        location = _post(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        before = client.get(location).text
        resend = _post(client, f"{location}/hl7/resend")
        after = client.get(location).text
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", before) == ["拒否", "送信待ち"]
    assert "unknown patient" in before and "<td class=\"mono\">AE</td>" in before
    assert 'action="' + location + '/hl7/resend"' in before and "再送信</button>" in before
    assert resend.status_code == 303 and resend.headers["location"] == location
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", after) == ["送信完了", "送信完了"]
    assert "再送信" not in after
    assert receiver.received[0] == receiver.received[1]


def test_unreachable_receiver_shows_failure(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store, port=1) as (client, _):
        location = _post(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        page = client.get(location).text
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", page) == ["送信失敗", "送信待ち"]
    assert "再送信</button>" in page


def test_post_without_csrf_token_is_refused(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        response = client.post(
            f"/reconciliation/{sop_uid}", data=_roster(), headers={"Origin": ORIGIN}
        )
        assert response.status_code == 403
        assert service.count_orders() == 0


def test_ordinary_order_has_no_hl7_section(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, service):
        order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
        page = client.get(f"/orders/{order.accession_number}").text
    assert "HL7 送信" not in page and "照合前" not in page


def test_detail_terms_for_reconciled_order(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, _):
        location = _post(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        page = client.get(location).text
    items = set(re.findall(r"<dt>([^<]+)</dt>", page))
    assert {"照合前の患者ID", "照合前の氏名"} <= items
    assert re.findall(r"<th>([^<]+)</th>", page.split("<h2>HL7 送信</h2>")[1].split("</thead>")[0]) == [
        "メッセージ", "状態", "ACK", "詳細", "送信日時", "回数",
    ]  # fmt: skip
