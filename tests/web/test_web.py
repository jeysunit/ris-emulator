"""Web 画面の試験（FastAPI の TestClient）."""

from __future__ import annotations

import base64
import re

import pytest
from fastapi.testclient import TestClient

from app.core.models import OrderStatus
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore
from app.web.app import create_app
from app.web.auth import PASSWORD_FILE_ENV, WebStartupError, startup_password
from tests.conftest import TODAY, new_order_service

ORIGIN = "http://127.0.0.1:8081"


def _client(config: AppConfig, service: OrderService, password: str | None = None) -> TestClient:
    app = create_app(config, password=password, service=service, start_mwl=False)
    return TestClient(app, base_url=ORIGIN)


def _token(client: TestClient) -> str:
    return client.app.state.csrf_token  # type: ignore[attr-defined]


def test_list_shows_orders(config: AppConfig, service: OrderService) -> None:
    orders = service.create_orders(OrderRequest(counts={"CT": 2}, scheduled_date=TODAY, seed=1))
    with _client(config, service) as client:
        response = client.get("/orders?date=2026-10-21")
    assert response.status_code == 200
    for order in orders:
        assert order.accession_number in response.text
        assert order.patient.name.ideographic.replace("^", " ") in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_station_name_is_shown(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    # 台帳より前に作った予約（装置の名前を持たない）
    legacy = order.model_copy(
        update={"accession_number": "RE202610209999", "scheduled_station_label": ""}
    )
    service.store.add_numbered_orders("legacy", 1, lambda _numbers, _exists: [legacy])
    with _client(config, service) as client:
        html = client.get("/orders?date=2026-10-21").text
        detail = client.get(f"/orders/{order.accession_number}").text
        legacy_detail = client.get(f"/orders/{legacy.accession_number}").text
    assert "<th>装置</th>" in html
    assert "CT1号機" in _row(html, order.accession_number)
    legacy_row = _row(html, legacy.accession_number)
    assert "号機" not in legacy_row and "CT01" in legacy_row
    assert "<dt>装置</dt><dd>CT1号機</dd>" in detail
    assert "<dt>装置</dt>" not in legacy_detail


def test_root_redirects(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = client.get("/", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/orders"


def test_create_from_form(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/orders/new")
        assert page.status_code == 200
        assert re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        response = client.post(
            "/orders",
            data={
                "csrf_token": _token(client),
                "count_CT": "3",
                "count_MR": "1",
                "date": "2026-10-21",
                "start": "10:00",
                "interval": "20",
                "patients": "random",
                "charset": "jis",
                "department": "外科",
                "seed": "5",
                "station_MR": "MR1号機",
                # 件数の無いモダリティの装置の欄は使わない
                "station_CR": "CR1号機",
            },
            headers={"Origin": ORIGIN},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/orders?date=2026-10-21"
    assert "順に使う" in page.text and "CT1号機（CT01）" in page.text
    assert 'name="station_ae"' not in page.text
    orders = service.list_orders()
    assert [o.modality for o in orders].count("CT") == 3
    assert {o.scheduled_station_label for o in orders} == {"CT1号機", "MR1号機"}
    html_rows = [o for o in orders if o.modality == "MR"]
    assert html_rows[0].scheduled_station_ae_title == "MR01"
    assert {o.requesting_service for o in orders} == {"外科"}
    assert {o.character_set.value for o in orders} == {"jis"}
    assert sorted({o.scheduled_time for o in orders if o.modality == "CT"}) == ["100000", "102000", "104000"]


def test_create_errors_are_shown(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = client.post(
            "/orders",
            data={"csrf_token": _token(client), "date": "2026-10-21", "start": "09:00"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 400
        assert "1 以上の件数" in response.text
        response = client.post(
            "/orders",
            data={"csrf_token": _token(client), "count_CT": "1", "date": "2026-10-21", "start": "09:00", "station_CT": "MR1号機"},
            headers={"Origin": ORIGIN},
        )
        # 別のモダリティの装置が送られた
        assert response.status_code == 400
        assert "CT の台帳に無い装置です: MR1号機" in response.text
    assert service.list_orders() == []


def test_post_requires_csrf_and_same_origin(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        no_token = client.post("/orders", data={"count_CT": "1"}, headers={"Origin": ORIGIN})
        assert no_token.status_code == 403
        cross = client.post(
            "/orders",
            data={"csrf_token": _token(client), "count_CT": "1"},
            headers={"Origin": "http://evil.example"},
        )
        assert cross.status_code == 403
    assert service.list_orders() == []


def test_status_change_with_htmx(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CR": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        response = client.post(
            f"/orders/{order.accession_number}/status",
            data={"status": "in_progress"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": _token(client), "HX-Request": "true"},
        )
        assert response.status_code == 200
        assert response.text.lstrip().startswith(f'<tr id="order-{order.accession_number}"')
        assert service.get(order.accession_number).status is OrderStatus.IN_PROGRESS
        missing = client.post(
            "/orders/NOPE/status",
            data={"status": "completed"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": _token(client)},
        )
        assert missing.status_code == 404
        bad = client.post(
            f"/orders/{order.accession_number}/status",
            data={"status": "done"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": _token(client)},
        )
        assert bad.status_code == 400


def _status_options(html: str, accession_number: str) -> list[str]:
    """一覧の行の状態の選択肢の値."""
    return re.findall(r'<option value="([a-z_]+)"', _row(html, accession_number))


def _row(html: str, accession_number: str) -> str:
    row = re.search(rf'<tr id="order-{accession_number}".*?</tr>', html, re.S)
    assert row is not None
    return row.group(0)


def test_list_offers_only_allowed_statuses(config: AppConfig, service: OrderService) -> None:
    scheduled, done = service.create_orders(
        OrderRequest(counts={"CT": 2}, scheduled_date=TODAY, seed=1)
    )
    service.set_status(done.accession_number, OrderStatus.COMPLETED)
    with _client(config, service) as client:
        html = client.get("/orders?date=2026-10-21").text
    assert _status_options(html, scheduled.accession_number) == [
        "scheduled",
        "in_progress",
        "completed",
        "cancelled",
    ]
    # 完了の行は選択肢を出さず、状態の名前だけ
    done_row = _row(html, done.accession_number)
    assert "<select" not in done_row and "完了" in done_row


def test_final_status_change_is_rejected(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    cancelled = service.set_status(order.accession_number, OrderStatus.CANCELLED)
    with _client(config, service) as client:
        htmx = client.post(
            f"/orders/{order.accession_number}/status",
            data={"status": "in_progress"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": _token(client), "HX-Request": "true"},
        )
        assert htmx.status_code == 400
        form = client.post(
            f"/orders/{order.accession_number}/status",
            data={"status": "scheduled", "csrf_token": _token(client)},
            headers={"Origin": ORIGIN},
        )
        assert form.status_code == 400
        assert "取消の予約は予定に変更できません" in form.text
        detail = client.get(f"/orders/{order.accession_number}").text
    stored = service.get(order.accession_number)
    assert stored.status is OrderStatus.CANCELLED
    assert stored.updated_at == cancelled.updated_at
    # 終わりの状態の詳細には、状態を変えるフォームを出さない
    assert "状態を変える" not in detail


def test_in_progress_offers_discontinued(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    service.set_status(order.accession_number, OrderStatus.IN_PROGRESS)
    with _client(config, service) as client:
        html = client.get("/orders?date=2026-10-21").text
    assert _status_options(html, order.accession_number) == [
        "scheduled",
        "in_progress",
        "completed",
        "cancelled",
        "discontinued",
    ]


def test_retake_button_only_in_new_order_mode(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    service.set_status(order.accession_number, OrderStatus.COMPLETED)
    with _client(config, service) as client:
        detail = client.get(f"/orders/{order.accession_number}").text
        assert "撮り直しの予約を作る" not in detail
        refused = client.post(
            f"/orders/{order.accession_number}/retake",
            data={"csrf_token": _token(client)},
            headers={"Origin": ORIGIN},
        )
        assert refused.status_code == 400
    assert len(service.list_orders()) == 1


def test_retake_from_detail(config: AppConfig, store: OrderStore) -> None:
    retaking = new_order_service(config, store)
    web_config = retaking.config
    scheduled, done = retaking.create_orders(
        OrderRequest(counts={"CT": 2}, scheduled_date=TODAY, seed=1)
    )
    retaking.set_status(done.accession_number, OrderStatus.COMPLETED)
    with _client(web_config, retaking) as client:
        # 予定の予約にはボタンを出さない
        assert "撮り直しの予約を作る" not in client.get(f"/orders/{scheduled.accession_number}").text
        detail = client.get(f"/orders/{done.accession_number}").text
        assert "撮り直しの予約を作る" in detail
        response = client.post(
            f"/orders/{done.accession_number}/retake",
            data={"csrf_token": _token(client), "date": "2026-10-21", "start": "15:00"},
            headers={"Origin": ORIGIN},
            follow_redirects=False,
        )
        assert response.status_code == 303
        retake_url = response.headers["location"]
        retake_page = client.get(retake_url).text
        original_page = client.get(f"/orders/{done.accession_number}").text
    retake = retaking.list_retakes(done.accession_number)[0]
    assert retake_url == f"/orders/{retake.accession_number}"
    assert retake.scheduled_time == "150000"
    assert f'<a href="/orders/{done.accession_number}">' in retake_page and "撮り直しの元" in retake_page
    assert f'<a href="/orders/{retake.accession_number}">' in original_page


def test_detail_shows_mpps(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    steps = [(order.accession_number, order.scheduled_procedure_step_id)]
    service.store.create_mpps("1.2.392.1", steps, {})
    service.store.update_mpps("1.2.392.1", "COMPLETED", {})
    with _client(config, service) as client:
        detail = client.get(f"/orders/{order.accession_number}").text
    assert "1.2.392.1" in detail and "COMPLETED" in detail
    # MPPS で完了になったので、終わりの状態の表示になる
    assert "状態を変える" not in detail


def test_detail_page(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"MR": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        response = client.get(f"/orders/{order.accession_number}")
        assert response.status_code == 200
        assert order.study_instance_uid in response.text
        assert "Scheduled Procedure Step Sequence" in response.text
        assert client.get("/orders/NOPE").status_code == 404


def test_host_header_is_checked_on_loopback(config: AppConfig, service: OrderService) -> None:
    app = create_app(config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url="http://attacker.example") as client:
        assert client.get("/orders").status_code == 400


def test_basic_auth(config: AppConfig, service: OrderService) -> None:
    with _client(config, service, password="s3cret") as client:
        assert client.get("/orders").status_code == 401
        token = base64.b64encode(b"ris:s3cret").decode()
        assert client.get("/orders", headers={"Authorization": f"Basic {token}"}).status_code == 200
        wrong = base64.b64encode(b"ris:nope").decode()
        assert client.get("/orders", headers={"Authorization": f"Basic {wrong}"}).status_code == 401


def test_startup_password_rules(tmp_path) -> None:
    assert startup_password("127.0.0.1", {}) is None
    with pytest.raises(WebStartupError):
        startup_password("0.0.0.0", {})
    secret = tmp_path / "password"
    secret.write_text("abc\n", encoding="utf-8")
    assert startup_password("0.0.0.0", {PASSWORD_FILE_ENV: str(secret)}) == "abc"
    empty = tmp_path / "empty"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(WebStartupError):
        startup_password("0.0.0.0", {PASSWORD_FILE_ENV: str(empty)})


def test_lifespan_starts_and_stops_mwl(config: AppConfig, service: OrderService) -> None:
    app = create_app(config, password=None, service=service, start_mwl=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert app.state.mwl.running
        assert "待ち受け中" in client.get("/orders").text
    assert not app.state.mwl.running
