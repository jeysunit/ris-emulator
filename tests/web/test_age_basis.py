"""年齢を数える日の試験（docs/spec/03_web_cli.md）：検査に結び付く画面は検査日の時点、無いときは開いた日."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.wareki import age_on, parse_date
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore
from app.web.app import count_day, create_app, study_day
from tests.conftest import NOW, TODAY, add_unscheduled_mpps

ORIGIN = "http://127.0.0.1:8081"
OPENED = date(2027, 1, 1)  # 画面を開いた日。MPPS の開始日（2026/10/21）より後


def test_count_day_uses_the_study_day_and_falls_back_to_the_opened_day() -> None:
    assert count_day("20260410", OPENED) == date(2026, 4, 10)
    assert count_day("", OPENED) == OPENED
    assert count_day("20261399", OPENED) == OPENED


def test_study_day_prefers_the_mpps_start_and_then_the_received_day() -> None:
    received = "2026-10-22T09:00:00+09:00"
    assert study_day(SimpleNamespace(started_date="20261021", received_at=received)) == "20261021"
    assert study_day(SimpleNamespace(started_date="", received_at=received)) == "20261022"
    assert study_day(SimpleNamespace(started_date="", received_at="not a time")) == ""


def _client(config: AppConfig, store: OrderStore) -> tuple[TestClient, OrderService]:
    service = OrderService(config, store, today=lambda: OPENED, now=lambda: NOW)
    app = create_app(config, password=None, service=service, start_mwl=False)
    return TestClient(app, base_url=ORIGIN), service


def test_order_banner_counts_the_age_on_the_scheduled_day(config: AppConfig, store: OrderStore) -> None:
    client, service = _client(config, store)
    scheduled = date(TODAY.year + 10, TODAY.month, TODAY.day)
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=scheduled, seed=1))[0]
    born = parse_date(order.patient.birth_date)
    assert born is not None
    on_study, on_open = age_on(born, scheduled), age_on(born, OPENED)
    assert on_study != on_open
    with client:
        page = client.get(f"/orders/{order.accession_number}").text
    assert f"・{on_study}歳）" in page and f"・{on_open}歳）" not in page


def test_unreconciled_list_and_banner_count_the_age_on_the_mpps_start_day(
    config: AppConfig, store: OrderStore
) -> None:
    # 1975/10/22 生まれ。MPPS の開始日 2026/10/21 は誕生日の前日で 50 歳、開いた日 2027/01/01 では 51 歳
    sop_uid, _ = add_unscheduled_mpps(store, birth_date="19751022")
    client, _ = _client(config, store)
    with client:
        listing = client.get("/reconciliation").text
        banner = client.get(f"/reconciliation/{sop_uid}").text
    assert "1975/10/22 (S50・50歳)" in listing and "51歳" not in listing
    assert "（昭50・50歳）" in banner and "51歳" not in banner


def test_order_list_side_banner_follows_the_scheduled_day(config: AppConfig, store: OrderStore) -> None:
    client, service = _client(config, store)
    first = date(TODAY.year + 10, TODAY.month, TODAY.day)
    later = date(TODAY.year + 11, TODAY.month, TODAY.day)
    ages = []
    for scheduled in (first, later):
        order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=scheduled, seed=1))[0]
        born = parse_date(order.patient.birth_date)
        assert born is not None
        with client:
            page = client.get(f"/orders?date_from={scheduled:%Y%m%d}&date_to={scheduled:%Y%m%d}").text
        ages.append(age_on(born, scheduled))
        assert order.accession_number in page
        assert f"・{ages[-1]}歳）" in page
        assert f"・{age_on(born, OPENED)}歳）" not in page
    assert ages[0] != ages[1]


def test_birth_after_the_count_day_shows_the_era_without_an_age(config: AppConfig, store: OrderStore) -> None:
    # 生年月日 2027/06/15 は MPPS の開始日 2026/10/21 より後。年齢は出さず、元号の括弧だけにする
    sop_uid, _ = add_unscheduled_mpps(store, birth_date="20270615")
    client, _ = _client(config, store)
    with client:
        listing = client.get("/reconciliation").text
        banner = client.get(f"/reconciliation/{sop_uid}").text
    assert "2027/06/15 (R9)" in listing
    assert "（令9）" in banner
    assert "歳）" not in banner
