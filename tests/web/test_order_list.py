"""予約の画面（openspec/changes/refine-order-list）の試験."""

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
            "予約": client.get("/orders").text,
            "予約作成": client.get("/orders/new").text,
            order.accession_number: client.get(f"/orders/{order.accession_number}").text,
        }
    for title, page in pages.items():
        nav = page.split('<nav class="sidenav"')[1].split("</nav>")[0]
        assert re.findall(r">([^<]+)</a>", nav) == ["予約", "予約作成", "一括作成", "未照合"]
        assert f"<title>{title} - ris-emulator</title>" in page
        selected_nav = re.findall(r'<a href="([^"]+)" class="nav-i" aria-current="page">', nav)
        assert selected_nav == ["/orders/new" if title == "予約作成" else "/orders"]
        assert '<nav' not in page.split('</header>')[0]
        head = page.split("</h1>")[0]
        assert "予約の一覧" not in head and "予約を作る" not in head
        # 帯は無く、版はヘッダーにだけ出る
        assert "<footer" not in page and "開発・試験用" not in page
        assert f'<span class="version">{__version__}</span>' in page.split("</header>")[0]
    assert "<h1>予約 <small>2026/10/21</small></h1>" in pages["予約"]
    assert "<h1>予約作成</h1>" in pages["予約作成"]
    # 詳細からの戻り先は、パンくずの「予約」（予定日を保つ）
    crumbs = pages[order.accession_number].split('<ol class="crumbs">')[1].split("</ol>")[0]
    assert re.findall(r'<a href="([^"]+)">([^<]+)</a>', crumbs) == [("/orders?date_from=2026-10-21", "予約")]
    assert "予約へ戻る" not in pages[order.accession_number]


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
        last = client.get(_links(client.get(_links(first)["次のページ"]).text)["次のページ"]).text
        beyond = client.get("/orders?page=99").text
    assert "1〜100 件目／全 230 件" in first
    assert len(re.findall(r'<tr id="order-', first)) == 100
    assert "前のページ" not in _links(first)
    assert "201〜230 件目／全 230 件" in last
    assert len(re.findall(r'<tr id="order-', last)) == 30
    assert "次のページ" not in _links(last) and _links(last)["前のページ"].endswith("page=2")
    assert "201〜230 件目／全 230 件" in beyond


def test_odd_page_numbers_fall_back_to_first_page(config: AppConfig, service: OrderService) -> None:
    service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))
    with _client(config, service) as client:
        # 「²」は str.isdigit() では数字だが int() で読めない。桁の多すぎる数は int() の上限を超える
        for page in ("%C2%B2", "9" * 5000, "-1", "abc", "0"):
            response = client.get(f"/orders?page={page}")
            assert response.status_code == 200, page
            assert "1〜1 件目／全 1 件" in response.text


def test_status_badges_and_six_columns(config: AppConfig, service: OrderService) -> None:
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
            # 完了（終わりの状態）へは、確認の窓の実行（confirmed=1）で変える
            data={"status": "completed", "confirmed": "1"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": client.app.state.csrf_token, "HX-Request": "true"},  # type: ignore[attr-defined]
        )
    assert row.status_code == 204 and row.headers["HX-Refresh"] == "true"
    assert "<th>状態</th>" in page
    rows = re.findall(r'<tr id="order-.*?</tr>', page, re.S)
    assert len(rows) == 5
    for row_html, kind in zip(rows, ("plan", "run", "done", "cancel", "stop"), strict=True):
        assert len(re.findall(r'<td[ >]', row_html)) == 6
        assert f'data-k="{kind}"' in row_html
        assert "<select" not in row_html


def test_status_select_guards_against_unsaved_values(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        page = client.get("/orders").text
        script = client.get("/static/app.js")
    # 送信中は選択を無効にし、失敗したら保存済みの状態（data-current）へ戻す
    select = re.search(r'<select name="status"[^>]*data-current=[^>]*>', page)
    assert select is not None
    assert 'hx-disabled-elt="find select, find button"' in page
    assert 'hx-swap="none"' in page and 'data-current="scheduled"' in select.group(0)
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


def _summary(page: str) -> dict[str, int]:
    return {label.strip(): int(count) for label, count in re.findall(
        r'class="sum"[^>]*>([^<]+)<span class="nbr">(\d+)</span>', page
    )}


def test_selection_summary_and_panel(config: AppConfig, service: OrderService) -> None:
    first, second = service.create_orders(OrderRequest(counts={"CT": 2}, scheduled_date=TODAY, seed=1))
    service.set_status(second.accession_number, OrderStatus.COMPLETED)
    with _client(config, service) as client:
        default = client.get("/orders").text
        chosen = client.get(f"/orders?selected={second.accession_number}").text
        invalid = client.get("/orders?selected=missing").text
        filtered = client.get("/orders?status=completed&modality=CT").text
        empty = client.get("/orders?q=missing").text
        patient = client.get("/orders", params={"q": f" {first.patient.patient_id} "}).text
        accession = client.get("/orders", params={"q": second.accession_number}).text
        response = client.post(
            f"/orders/{first.accession_number}/status", data={"status": "discontinued"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": client.app.state.csrf_token, "HX-Request": "true"},
        )
    for page in (default, invalid):
        assert f'<h2>予約 {first.accession_number}' in page
        assert re.search(rf'selected={first.accession_number}" aria-current="true"', page)
    assert f'<h2>予約 {second.accession_number}' in chosen
    assert "状態を変える" not in chosen
    assert f'href="/orders/{second.accession_number}" class="btn btn-primary">詳細を開く' in chosen
    assert re.findall(r'<dt>(.*?)</dt>', default) == [
        "氏名", "患者ID", "生年月日", "性別", "予定日時", "検査名", "装置", "依頼科"
    ]
    assert first.patient.patient_id in default and first.procedure.code in default
    assert first.scheduled_station_label in default and first.requesting_service in default
    assert _summary(default) == _summary(filtered) == {"すべて": 2, "予定": 1, "実施中": 0, "完了": 1, "取消": 0, "中止": 0}
    assert first.accession_number not in filtered and second.accession_number in filtered
    assert 'aria-label="選んだ予約"' not in empty and '<table' not in empty
    assert "条件に合う予約はありません。" in empty and _summary(empty)["すべて"] == 0
    assert _links(empty)["予約作成"] == "/orders/new"
    assert first.accession_number in patient and second.accession_number not in patient
    assert second.accession_number in accession and first.accession_number not in accession
    assert response.status_code == 400 and "HX-Refresh" not in response.headers
    assert 'data-current="scheduled"' in default


def test_query_and_status_survive_links(config: AppConfig, service: OrderService) -> None:
    orders = service.create_orders(OrderRequest(counts={"CT": 101}, scheduled_date=TODAY, interval_minutes=1, seed=1))
    # 同じ患者の予約を 101 件にして、検索とページ送りを同時に確かめる
    for order in orders[1:]:
        with service.store._connect() as conn:
            copied = order.model_copy(update={"patient": orders[0].patient})
            conn.execute("UPDATE orders SET patient_id = ?, body = ? WHERE accession_number = ?",
                         (copied.patient.patient_id, copied.model_dump_json(), copied.accession_number))
    query = orders[0].patient.patient_id
    with _client(config, service) as client:
        first = client.get("/orders", params={"q": query, "status": "scheduled", "modality": "CT", "selected": orders[2].accession_number}).text
        next_url = _links(first)["次のページ"]
        last = client.get(next_url).text
    assert f"q={query}" in next_url and "status=scheduled" in next_url and "modality=CT" in next_url
    assert "selected=" not in next_url
    assert f'<h2>予約 {orders[-1].accession_number}' in last
    for label in ("前日", "翌日", "前のページ"):
        url = _links(last)[label]
        assert f"q={query}" in url and "status=scheduled" in url and "modality=CT" in url
    summary_links = re.findall(r'<a href="([^"]+)" class="sum"', first)
    assert len(summary_links) == 6
    assert all(f"q={query}" in url and "modality=CT" in url for url in summary_links)
    assert 'class="sum" aria-current="true">予定' in first
