"""予約一覧の画面（openspec/changes/refine-order-list）の試験."""

from __future__ import annotations

import html
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from app import __version__
from app.core.models import OrderStatus
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.web.app import create_app
from tests.conftest import TODAY

ORIGIN = "http://127.0.0.1:8081"
TOMORROW = TODAY + timedelta(days=1)


def _client(config: AppConfig, service: OrderService) -> TestClient:
    return TestClient(create_app(config, password=None, service=service, start_mwl=False), base_url=ORIGIN)


def _links(page: str) -> dict[str, str]:
    """ボタンとリンクの文字 → URL."""
    return {
        text.strip(): html.unescape(href)
        for href, text in re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', page)
    }


def test_titles_and_nav(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        pages = {
            "予約一覧": client.get("/orders").text,
            "予約作成": client.get("/orders/new").text,
            order.accession_number: client.get(f"/orders/{order.accession_number}").text,
        }
    for title, page in pages.items():
        nav = page.split('<nav class="nav"')[1].split("</nav>")[0]
        assert re.findall(r">([^<]+)</a>", nav) == ["予約一覧", "予約作成"]
        assert f"<title>{title} - ris-emulator</title>" in page
        head = page.split("</h1>")[0]
        assert "予約の一覧" not in head and "予約を作る" not in head
        # 帯は無く、版はヘッダーにだけ出る
        assert "<footer" not in page and "開発・試験用" not in page
        assert f'<span class="version">{__version__}</span>' in page.split("</header>")[0]
    assert "<h1>予約一覧</h1>" in pages["予約一覧"]
    assert "<h1>予約作成</h1>" in pages["予約作成"]
    assert _links(pages[order.accession_number])["予約一覧へ"] == "/orders?date_from=2026-10-21"


def test_default_is_today_and_today_button(config: AppConfig, service: OrderService) -> None:
    today = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    later = service.create_orders(OrderRequest(counts={"MR": 1}, scheduled_date=TOMORROW, seed=2))[0]
    service.set_status(later.accession_number, OrderStatus.COMPLETED)
    with _client(config, service) as client:
        default = client.get("/orders").text
        other = client.get("/orders?date_from=2026-10-22&status=completed&modality=MR").text
    assert today.accession_number in default and later.accession_number not in default
    assert 'name="date_from" value="2026-10-21"' in default
    assert later.accession_number in other and today.accession_number not in other
    # 「本日」は引数の無い一覧（予定日は本日、状態とモダリティはすべて）
    assert _links(other)["本日"] == "/orders"
    assert "全日付" not in default and "date=all" not in default


def test_period(config: AppConfig, service: OrderService) -> None:
    first = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    second = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TOMORROW, seed=2))[0]
    with _client(config, service) as client:
        both = client.get("/orders?date_from=2026-10-21&date_to=2026-10-22").text
        legacy = client.get("/orders?date=2026-10-22").text
        longest = client.get("/orders?date_from=2026-10-01&date_to=2026-10-31")
        too_long = client.get("/orders?date_from=2026-10-01&date_to=2026-11-01")
        reverse = client.get("/orders?date_from=2026-10-22&date_to=2026-10-21")
        everything = client.get("/orders?date=all")
        broken = client.get("/orders?date_from=2026-13-40")
    assert both.index(first.accession_number) < both.index(second.accession_number)
    assert second.accession_number in legacy and first.accession_number not in legacy
    assert longest.status_code == 200
    assert too_long.status_code == 400 and "31日まで" in too_long.text
    assert first.accession_number not in too_long.text
    assert reverse.status_code == 400 and "終了日は開始日と同じ日か、後の日" in reverse.text
    assert everything.status_code == 400 and "開始日と終了日" in everything.text
    assert broken.status_code == 400
    # 入れた値はエラーのときもフォームに残る
    assert 'name="date_to" value="2026-11-01"' in too_long.text


def test_previous_and_next_day(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/orders?date_from=2026-10-24&date_to=2026-10-25&status=scheduled&modality=ct").text
    links = _links(page)
    assert links["翌日"] == "/orders?date_from=2026-10-25&date_to=2026-10-26&status=scheduled&modality=CT"
    assert links["前日"] == "/orders?date_from=2026-10-23&date_to=2026-10-24&status=scheduled&modality=CT"
    with _client(config, service) as client:
        edge = client.get("/orders?date_from=9999-12-31").text
    assert "翌日" not in _links(edge) and "前日" in _links(edge)


def test_pages(config: AppConfig, service: OrderService) -> None:
    for seed in (1, 2):
        service.create_orders(
            OrderRequest(counts={"CT": 200 if seed == 1 else 30}, scheduled_date=TODAY, interval_minutes=1, seed=seed)
        )
    with _client(config, service) as client:
        first = client.get("/orders").text
        last = client.get(_links(client.get(_links(first)["次の頁"]).text)["次の頁"]).text
        beyond = client.get("/orders?page=99").text
    assert "1〜100 件目／全 230 件" in first
    assert len(re.findall(r'<tr id="order-', first)) == 100
    assert "前の頁" not in _links(first)
    assert "201〜230 件目／全 230 件" in last
    assert len(re.findall(r'<tr id="order-', last)) == 30
    assert "次の頁" not in _links(last) and _links(last)["前の頁"].endswith("page=2")
    assert "201〜230 件目／全 230 件" in beyond


def test_odd_page_numbers_fall_back_to_first_page(config: AppConfig, service: OrderService) -> None:
    service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))
    with _client(config, service) as client:
        # 「²」は str.isdigit() では数字だが int() で読めない。桁の多すぎる数は int() の上限を超える
        for page in ("%C2%B2", "9" * 5000, "-1", "abc", "0"):
            response = client.get(f"/orders?page={page}")
            assert response.status_code == 200, page
            assert "1〜1 件目／全 1 件" in response.text


def test_status_column_class(config: AppConfig, service: OrderService) -> None:
    orders = service.create_orders(OrderRequest(counts={"CT": 5}, scheduled_date=TODAY, seed=1))
    for order, status in zip(
        orders[1:],
        (OrderStatus.IN_PROGRESS, OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.IN_PROGRESS),
        strict=True,
    ):
        service.set_status(order.accession_number, status)
    service.set_status(orders[4].accession_number, OrderStatus.DISCONTINUED)
    with _client(config, service) as client:
        page = client.get("/orders").text
        row = client.post(
            f"/orders/{orders[1].accession_number}/status",
            data={"status": "completed"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": client.app.state.csrf_token, "HX-Request": "true"},  # type: ignore[attr-defined]
        ).text
    assert '<th class="col-status">状態</th>' in page
    # すべての状態の行（予定・実施中・完了・取消・中止）で、状態のセルに同じ class が付く
    assert page.count('<td class="col-status">') == 5
    assert row.count('<td class="col-status">') == 1


def test_status_select_guards_against_unsaved_values(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        page = client.get("/orders").text
        script = client.get("/static/app.js")
    # 送信中は選択を無効にし、失敗したら保存済みの状態（data-current）へ戻す
    select = re.search(r"<select name=\"status\" aria-label=[^>]*>", page)
    assert select is not None
    assert 'hx-disabled-elt="this"' in select.group(0) and 'data-current="scheduled"' in select.group(0)
    assert '<p id="request-error" class="error" role="alert" hidden></p>' in page
    assert '<script src="/static/app.js" defer></script>' in page
    assert script.status_code == 200
    assert "htmx:responseError" in script.text and "htmx:sendError" in script.text
    assert order.accession_number in page


def test_unreadable_date_message_uses_screen_format(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = client.get("/orders?date_from=2026-13-40")
    assert response.status_code == 400
    assert "予定日は YYYY-MM-DD の日付で指定してください" in response.text
    assert "tomorrow" not in response.text
