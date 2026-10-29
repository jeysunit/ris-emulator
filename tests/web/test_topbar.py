"""上の帯（ナビの開閉・製品名・接続の状態・表示）と左のナビの絵、バージョン情報の試験."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.config import AppConfig
from app.services.order_service import OrderService
from app.web.app import create_app
from tests.conftest import TEST_VERSION

ORIGIN = "http://127.0.0.1:8081"
STATIC = Path(__file__).resolve().parents[2] / "app" / "web" / "static"


def _header(config: AppConfig, service: OrderService, *, start_mwl: bool) -> str:
    app = create_app(config, password=None, service=service, start_mwl=start_mwl)
    with TestClient(app, base_url=ORIGIN) as client:
        return client.get("/orders").text.split("</header>")[0]


def test_topbar_order_and_connection_popover(config: AppConfig, service: OrderService) -> None:
    header = _header(config, service, start_mwl=True)
    # 並びは ナビの開閉 → 製品名 → 接続の状態 → 表示。製品名の横に版は出さない
    order = [
        header.index('data-act="nav"'),
        header.index('class="brand">ris-emulator</a>'),
        header.index('popovertarget="conn-pop"'),
        header.index('data-act="theme"'),
    ]
    assert order == sorted(order)
    assert 'class="ver"' not in header and TEST_VERSION not in header
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
        sprite = client.get("/static/ui-kit/icons.svg").text
        theme = client.get("/static/theme.js").text
        script = client.get("/static/app.js").text
    nav = page.split('<nav class="sidenav"')[1].split("</nav>")[0]
    icons = re.findall(r'<use href="/static/ui-kit/icons.svg#(i-[a-z]+)"/></svg><span class="t">', nav)
    assert icons == ["i-list", "i-plus", "i-plus", "i-inbox", "i-info"]
    for name in [*icons, "i-menu", "i-sun", "i-moon"]:
        assert f'<symbol id="{name}" viewBox="0 0 24 24"' in sprite
    # 地は描く前に決める（head の同期の script）。覚えが無ければ端末の設定に従う
    head = page.split("</head>")[0]
    assert head.index('<script src="/static/theme.js"></script>') < head.index("/static/ui-kit/tokens.css")
    assert 'localStorage.getItem("ris-theme")' in theme and 'localStorage.getItem("ris-nav")' in theme
    assert '"ris-theme"' in script and 'classList.toggle("collapsed"' in script
    assert (STATIC / "theme.js").is_file()


def test_version_page_is_in_the_admin_group_and_shows_name_and_version(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILD_COMMIT", raising=False)
    app = create_app(config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        page = client.get("/orders").text
        version = client.get("/version")
    # 左のナビの群「管理」の最後の項目。項目の名前と頁の題は同じ語
    nav = page.split('<nav class="sidenav"')[1].split("</nav>")[0]
    assert re.findall(r'<p class="nav-g">([^<]+)</p>', nav) == ["業務", "管理"]
    assert nav.rstrip().endswith('<span class="t">バージョン情報</span></a>')
    assert version.status_code == 200
    assert "<title>バージョン情報 - ris-emulator</title>" in version.text
    assert '<h1>バージョン情報</h1>' in version.text
    assert f'<dd data-testid="app-version">{TEST_VERSION}</dd>' in version.text
    # 項目名と値の一覧は、3 製品共通の部品（kv）で組む
    assert '<dl class="kv" data-testid="version-info">' in version.text
    # 今いる頁の印は、この頁の項目だけに付く。ビルドの commit は渡されていないので出さない
    current = re.findall(r'<a href="([^"]+)" class="nav-i" aria-current="page"', version.text)
    assert current == ["/version"]
    assert "build-commit" not in version.text


def test_version_page_shows_build_commit_only_when_it_is_valid(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        monkeypatch.setenv("BUILD_COMMIT", " A1B2C3D4E5F6 ")
        assert 'data-testid="build-commit">a1b2c3d4e5f6</dd>' in client.get("/version").text
        for bad in ("", "abc12", "g" * 12, "a" * 41, "a1b2c3d; echo"):
            monkeypatch.setenv("BUILD_COMMIT", bad)
            assert "build-commit" not in client.get("/version").text


def test_version_page_needs_the_password_when_one_is_required(
    config: AppConfig, service: OrderService
) -> None:
    app = create_app(config, password="s3cret-for-test", service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/version").status_code == 401
