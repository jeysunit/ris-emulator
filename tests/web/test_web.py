"""Web 画面の試験（FastAPI の TestClient）."""

from __future__ import annotations

import base64
import re

import pytest
from fastapi.testclient import TestClient

from app.core.models import OrderStatus
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.web.app import create_app
from app.web.auth import PASSWORD_FILE_ENV, WebStartupError, startup_password
from tests.conftest import TODAY

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
            },
            headers={"Origin": ORIGIN},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/orders?date=2026-10-21"
    orders = service.list_orders()
    assert [o.modality for o in orders].count("CT") == 3
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
            data={"csrf_token": _token(client), "count_CT": "1", "date": "2026-10-21", "start": "09:00", "station_ae": "BAD\\AE"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 400
        assert "AE タイトル" in response.text
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
