"""終わりの状態（完了・取消・中止）へ変える前の確認の窓の試験（docs/spec/03_web_cli.md 3 章）."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.core.models import OrderStatus
from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.web.app import create_app
from tests.conftest import TODAY

ORIGIN = "http://127.0.0.1:8081"


def _client(config: AppConfig, service: OrderService) -> TestClient:
    app = create_app(config, password=None, service=service, start_mwl=False)
    return TestClient(app, base_url=ORIGIN)


def _post(client: TestClient, accession_number: str, *, htmx: bool = False, **data: str):  # noqa: ANN202
    headers = {"Origin": ORIGIN}
    if htmx:
        headers.update({"X-CSRF-Token": client.app.state.csrf_token, "HX-Request": "true"})  # type: ignore[attr-defined]
    return client.post(
        f"/orders/{accession_number}/status",
        data={"csrf_token": client.app.state.csrf_token, **data},  # type: ignore[attr-defined]
        headers=headers,
        follow_redirects=False,
    )


def _dialogs(page: str) -> dict[str, str]:
    """状態の確認の窓（状態の値 → 窓の HTML）."""
    return dict(re.findall(r'<dialog id="dlg-status-([a-z_]+)"(.*?)</dialog>', page, re.S))


def test_detail_has_a_dialog_for_each_final_status(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    service.set_status(order.accession_number, OrderStatus.IN_PROGRESS)
    with _client(config, service) as client:
        page = client.get(f"/orders/{order.accession_number}").text
    dialogs = _dialogs(page)
    assert sorted(dialogs) == ["cancelled", "completed", "discontinued"]
    name = order.patient.name.ideographic.replace("^", " ")
    cancelled = dialogs["cancelled"]
    # 閉じた形で置き、app.js が「状態を変える」で開く
    assert " open" not in cancelled.split(">", 1)[0]
    assert f"{order.accession_number}（{name}・{order.procedure.name}）を取消にしますか？" in cancelled
    assert "取消にすると、ワークリストに出なくなります。状態は戻せません。" in cancelled
    # 照合で作っていない予約は HL7 を送らない
    assert "ORM" not in cancelled
    assert '<input type="hidden" name="status" value="cancelled">' in cancelled
    assert '<input type="hidden" name="confirmed" value="1">' in cancelled
    assert "hx-post" not in cancelled
    assert re.findall(r"<button[^>]*>([^<]+)</button>", cancelled) == ["キャンセル", "取消にする"]
    assert 'class="btn btn-danger fill">取消にする' in cancelled
    assert 'class="btn btn-primary">完了にする' in dialogs["completed"]


def test_final_status_without_confirmation_opens_the_dialog(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        form = _post(client, order.accession_number, status="cancelled")
        htmx = _post(client, order.accession_number, htmx=True, status="cancelled")
        assert service.get(order.accession_number).status is OrderStatus.SCHEDULED
        # 戻せる変更（実施中）は今までどおり窓なしで変える
        running = _post(client, order.accession_number, status="in_progress")
        assert service.get(order.accession_number).status is OrderStatus.IN_PROGRESS
        confirmed = _post(client, order.accession_number, htmx=True, status="completed", confirmed="1")
    assert form.status_code == 200
    dialog = _dialogs(form.text)["cancelled"]
    assert "data-show-modal open" in dialog.split(">", 1)[0]
    assert htmx.status_code == 400 and "HX-Refresh" not in htmx.headers
    assert running.status_code == 303
    assert confirmed.status_code == 204 and confirmed.headers["HX-Refresh"] == "true"
    assert service.get(order.accession_number).status is OrderStatus.COMPLETED


def test_invalid_transition_is_still_refused(config: AppConfig, service: OrderService) -> None:
    """窓を出すのは変えられる状態だけ。変えられない状態は今までどおり断る."""
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        response = _post(client, order.accession_number, status="discontinued")
        missing = _post(client, "NOPE", status="cancelled")
    assert response.status_code == 400 and "data-show-modal open" not in response.text
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED
    assert missing.status_code == 404


def test_list_panel_dialog_posts_with_htmx(config: AppConfig, service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    with _client(config, service) as client:
        page = client.get("/orders").text
    panel = page.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]
    dialog = _dialogs(panel)["cancelled"]
    assert f'hx-post="/orders/{order.accession_number}/status" hx-swap="none"' in dialog
    assert "取消にする" in dialog
    # 検索の帯（GET）にも状態の選択がある。窓を開くのは POST の状態の変更のフォームだけ
    assert '<form method="get" action="/orders" class="filters searchband">' in page
    with _client(config, service) as client:
        script = client.get("/static/app.js").text
    assert 'form.method.toLowerCase() !== "post"' in script
    assert r"/^\/orders\/[^/]+\/status$/.test(action)" in script
