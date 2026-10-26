"""上の帯（ナビの開閉・製品名と版・接続の状態・表示）と左のナビの絵の試験."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.services.config import AppConfig
from app.services.order_service import OrderService
from app.web.app import create_app

ORIGIN = "http://127.0.0.1:8081"
STATIC = Path(__file__).resolve().parents[2] / "app" / "web" / "static"


def _header(config: AppConfig, service: OrderService, *, start_mwl: bool) -> str:
    app = create_app(config, password=None, service=service, start_mwl=start_mwl)
    with TestClient(app, base_url=ORIGIN) as client:
        return client.get("/orders").text.split("</header>")[0]


def test_topbar_order_and_connection_popover(config: AppConfig, service: OrderService) -> None:
    header = _header(config, service, start_mwl=True)
    # 並びは ナビの開閉 → 製品名と版 → 接続の状態 → 表示
    order = [
        header.index('data-act="nav"'),
        header.index('class="brand">ris-emulator</a>'),
        header.index(f'<span class="ver">{__version__}</span>'),
        header.index('popovertarget="conn-pop"'),
        header.index('data-act="theme"'),
    ]
    assert order == sorted(order)
    assert 'aria-expanded="true" aria-controls="sidenav"' in header
    # 閉じているときは全体の状態の札 1 つ。中身は標準の popover で、MWL の待ち受けと HL7 の送信先
    button = header.split('popovertarget="conn-pop"')[1].split("</button>")[0]
    assert '<span class="st" data-k="ok">接続中</span>' in button
    pop = header.split('<div id="conn-pop" popover class="pop"')[1].split("</div>")[0]
    assert re.findall(r"<dt>([^<]+)</dt>", pop) == ["待ち受け MWL", "送信先 HL7"]
    assert f"<b>{config.mwl.ae_title}</b>" in pop and '<span class="st" data-k="listen">待ち受け中</span>' in pop
    assert f"{config.hl7.host}:{config.hl7.port}" in pop
    # 帯に住所や塗りの札を出さない（住所は popover の中だけ）
    outside = header.replace(pop, "")
    assert "badge" not in header and f":{config.mwl.port}" not in outside


def test_topbar_when_mwl_is_stopped(config: AppConfig, service: OrderService) -> None:
    header = _header(config, service, start_mwl=False)
    assert '<span class="st" data-k="ng">一部が接続不可</span>' in header
    assert '<span class="st" data-k="ng">停止</span>' in header


def test_nav_items_have_icons_and_theme_is_remembered(config: AppConfig, service: OrderService) -> None:
    app = create_app(config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        page = client.get("/orders").text
        sprite = client.get("/static/icons/icons.svg").text
        theme = client.get("/static/theme.js").text
        script = client.get("/static/app.js").text
    nav = page.split('<nav class="sidenav"')[1].split("</nav>")[0]
    icons = re.findall(r'<use href="/static/icons/icons.svg#([a-z]+)"/></svg><span class="t">', nav)
    assert icons == ["orders", "new", "batch", "reconciliation"]
    for name in [*icons, "menu", "sun", "moon"]:
        assert f'<symbol id="{name}" viewBox="0 0 24 24">' in sprite
    # 地は描く前に決める（head の同期の script）。覚えが無ければ端末の設定に従う
    head = page.split("</head>")[0]
    assert head.index('<script src="/static/theme.js"></script>') < head.index("/static/ui-kit/tokens.css")
    assert 'localStorage.getItem("ris-theme")' in theme and 'localStorage.getItem("ris-nav")' in theme
    assert '"ris-theme"' in script and 'classList.toggle("collapsed"' in script
    assert (STATIC / "theme.js").is_file()
