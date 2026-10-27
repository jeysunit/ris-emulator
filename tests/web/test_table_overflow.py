"""一覧の表が幅に収まらないとき（docs/spec/03_web_cli.md 3.1）：頁を横に動かさず、操作の列を切らない.

ブラウザでの寸法（幅 390・1280 で、頁が横に動かず、操作のボタンが表の包みの中にあり押せる）は、
この試験では測れない（ブラウザの試験の仕組みを持たない）。ここでは、そのための CSS の規則と、
未照合の表の操作の列の印（`.act`）があることを確かめる。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.services.config import AppConfig
from app.services.store import OrderStore
from app.web.app import create_app
from tests.conftest import add_unscheduled_mpps

APP_CSS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "app.css"


def _rules(selector: str) -> str:
    """selector を末尾に持つ規則の中身を、空白を除いてつないだもの."""
    css = APP_CSS.read_text(encoding="utf-8")
    bodies = re.findall(r"(?:^|[\s,{}])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert bodies, f"{selector} の規則が無い"
    return "".join(re.sub(r"\s+", "", body) for body in bodies)


def test_action_column_is_pinned_to_the_right_edge() -> None:
    pinned = _rules(".tbl td.act")
    assert "position:sticky" in pinned and "right:0" in pinned
    assert "var(--color-background)" in pinned
    assert "var(--color-muted)" in _rules(".tbl tbody tr:hover td.act")
    assert "var(--color-selected)" in _rules(".tbl tbody tr[data-selected=true] td.act")


def test_narrow_layout_keeps_the_column_shrinkable() -> None:
    # 狭い画面で右の区画が一覧の下へ回るとき、列を 1fr のままにすると表の幅で頁が広がる
    narrow = re.sub(r"\s+", "", APP_CSS.read_text(encoding="utf-8"))
    assert "@media(max-width:900px){.split-h{grid-template-columns:minmax(0,1fr);}}" in narrow
    # ui-kit は本文の幅が 1000px 未満のとき（@container）にも 1fr にするので、こちらも覆う
    assert "@container(max-width:1000px){.split-h{grid-template-columns:minmax(0,1fr);}}" in narrow


def test_reconciliation_table_marks_its_action_column(config: AppConfig, store: OrderStore) -> None:
    add_unscheduled_mpps(store)
    app = create_app(config, password=None, start_mwl=False)
    with TestClient(app, base_url="http://127.0.0.1:8081") as client:
        page = client.get("/reconciliation").text

    table = page.split("<table", 1)[1].split("</table>", 1)[0]
    assert '<th class="act">' in table
    assert re.search(r'<td class="nowrap act"><a href="/reconciliation/[^"]+" class="btn btn-row">照合</a>', table)
