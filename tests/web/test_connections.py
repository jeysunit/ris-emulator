"""接続先の画面（/connections）と HL7 の送信先の接続確認（docs/spec/03_web_cli.md 3.1）."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import socket
import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.hl7.mllp import (
    REASON_NO_RESPONSE,
    REASON_REFUSED,
    REASON_UNKNOWN_HOST,
    ConnectionCheck,
    check_connection,
)
from app.services.config import AppConfig
from app.services.order_service import OrderService
from app.web.app import create_app
from tests.hl7.stub import stub_receiver

ORIGIN = "http://127.0.0.1:8081"


def _client(config: AppConfig, service: OrderService, *, start_mwl: bool = True) -> TestClient:
    app = create_app(config, password=None, service=service, start_mwl=start_mwl)
    return TestClient(app, base_url=ORIGIN)


def _post(client: TestClient, path: str):  # noqa: ANN202
    return client.post(
        path,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.app.state.csrf_token,  # type: ignore[attr-defined]
            "HX-Request": "true",
        },
    )


def _hl7_result(result: ConnectionCheck, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.web.connection.check_connection", lambda host, port, timeout: result)


def test_page_has_the_table_and_the_listening_section(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/connections").text
    assert "<title>接続先 - ris-emulator</title>" in page and "<h1>接続先</h1>" in page
    # 左のナビの群「接続」の項目で、いまの頁に印が付く
    nav = page.split('<nav class="sidenav"')[1].split("</nav>")[0]
    assert re.findall(r'<p class="nav-g">([^<]+)</p>', nav) == ["業務", "接続", "管理"]
    assert re.findall(r'<a href="([^"]+)" class="nav-i" aria-current="page"', nav) == ["/connections"]
    # HL7 の送信先の表：列は部品集の接続先の表のとおり。HL7 の AEタイトルは「—」
    table = page.split('<table class="tbl conn">')[1].split("</table>")[0]
    assert re.findall(r"<th>([^<]+)</th>", table) == ["名称", "種類", "AEタイトル", "ホスト名:ポート番号", "最後の接続確認"]
    assert '<span class="sr">操作</span>' in table
    row = table.split("<tbody>")[1]
    assert f'<span class="main-c">{config.hl7.receiving_application}</span>' in row
    assert "<td>HL7</td>" in row and '<span class="mono">—</span>' in row
    assert f'<span class="mono">{config.hl7.host}:{config.hl7.port}</span>' in row
    # まだ確かめていない確かめられる相手は札「未確認」
    assert '<td class="res"><span class="st" data-k="plan">未確認</span></td>' in row
    assert 'hx-post="/connections/check?target=hl7"' in row and ">接続確認</button>" in row
    # 区画の見出しの右に「すべて接続確認」（副）。見出しの横に説明の文は置かない
    assert re.search(r'<h2 class="hd">HL7 の送信先<span class="acts"><button type="button" class="btn" [^>]*>.*すべて接続確認</button>', page, re.S)
    # 待ち受けの区画：MWL の名前・札・住所（表には入れない）
    listening = page.split('<h2 class="hd">待ち受け</h2>')[1]
    assert f"<b>{config.mwl.ae_title}</b>" in listening and 'data-k="listen">待ち受け中</span>' in listening
    assert config.mwl.ae_title not in table
    # 押した直後の知らせの欄は、最初から読み上げの欄として置く
    assert re.search(r'<div id="conn-notice" role="status" aria-live="polite" data-unreadable="接続を確かめられませんでした。"></div>', page)


def test_page_and_popover_show_the_same_partners_and_marks(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hl7_result(ConnectionCheck(False, REASON_REFUSED), monkeypatch)
    with _client(config, service) as client:
        _post(client, "/connections/check?target=all")
        page = client.get("/connections").text
    pop = page.split('<div id="conn-pop" popover class="pop"')[1].split("</div>")[0]
    body = page.split('<main class="main">')[1]
    for kind, label in (("listen", "待ち受け中"), ("ng", "失敗")):
        assert f'<span class="st" data-k="{kind}">{label}</span>' in pop
        assert f'<span class="st" data-k="{kind}">{label}</span>' in body
    # 同じ時刻（確かめた時刻）が両方に出る
    assert set(re.findall(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", pop)) == set(re.findall(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", body))


def test_check_all_updates_the_table_the_notice_and_the_top_bar(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hl7_result(ConnectionCheck(True), monkeypatch)
    with _client(config, service) as client:
        response = _post(client, "/connections/check?target=all")
        after = client.get("/connections").text
    body = response.text
    assert response.status_code == 200
    # 表の行：成功の札と確かめた時刻
    assert re.search(r'<td class="res"><span class="st" data-k="ok">成功</span> <span class="when">\d{4}/\d{2}/\d{2} \d{2}:\d{2}</span></td>', body)
    assert "<span class=\"why\">" not in body
    # 待ち受け（MWL）も確かめる
    assert re.search(r'data-k="listen">待ち受け中</span>.*<span class="xs label">\d{4}/\d{2}/\d{2} \d{2}:\d{2}</span>', body)
    # 上の知らせ（読み上げの欄の中身）・上の帯の札・popover を同じ応答で差し替える
    target = f"{config.hl7.receiving_application}（{config.hl7.host}:{config.hl7.port}）"
    assert f'<div hx-swap-oob="innerHTML:#conn-notice"><div class="notice" data-k="ok"><svg class="ic" aria-hidden="true"><use href="/static/ui-kit/icons.svg#i-check"/></svg><div>{target}に接続できました。</div></div></div>' in body
    assert 'hx-swap-oob="innerHTML:#conn-pop"' in body
    assert '<span class="st" id="conn-state" data-k="ok" hx-swap-oob="true">接続中</span>' in body
    # 結果は覚えていて、読み直した画面にも残る
    assert 'data-k="ok">成功</span>' in after


@pytest.mark.parametrize(
    ("reason", "next_step"),
    [
        (REASON_NO_RESPONSE, "相手の電源とネットワーク、ホスト名・ポート番号（hl7.host・hl7.port）を確かめてください。"),
        (REASON_REFUSED, "相手が HL7 を待ち受けているか、ポート番号（hl7.port）が合っているかを確かめてください。"),
        (REASON_UNKNOWN_HOST, "ホスト名（hl7.host）の綴りと名前解決の設定を確かめてください。"),
    ],
)
def test_check_failure_shows_reason_and_next_step(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch, reason: str, next_step: str
) -> None:
    _hl7_result(ConnectionCheck(False, reason, "英語の元の文"), monkeypatch)
    with _client(config, service) as client:
        body = _post(client, "/connections/check?target=hl7").text
    # 表の列は「なぜか」の 1 句だけ。英語の元の文は出さない
    assert re.search(
        rf'<td class="res"><span class="st" data-k="ng">失敗</span> <span class="when">[^<]+</span> <span class="why">{reason}</span></td>', body
    )
    assert "英語の元の文" not in body
    # 知らせは 何が起きたか・なぜか・次にすること
    target = f"{config.hl7.receiving_application}（{config.hl7.host}:{config.hl7.port}）"
    assert f"<div>{target}に接続できません。{reason}。{next_step}</div>" in body
    # 全体の札も下がる
    assert 'data-k="ng" hx-swap-oob="true">一部が接続不可</span>' in body


def test_check_hl7_row_does_not_probe_the_mwl(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hl7_result(ConnectionCheck(True), monkeypatch)
    with _client(config, service) as client:
        body = _post(client, "/connections/check?target=hl7").text
    # 行の「接続確認」は送信先だけ。待ち受けの時刻は付かない
    assert not re.search(r'data-k="listen">待ち受け中</span>.*<span class="xs label">\d{4}/\d{2}/\d{2}', body.split("</section>")[1])


def test_check_rejects_an_unknown_target_and_needs_the_token(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        unknown = _post(client, "/connections/check?target=mwl")
        no_token = client.post("/connections/check", headers={"Origin": ORIGIN, "HX-Request": "true"})
    assert unknown.status_code == 400
    assert no_token.status_code == 403


def test_popover_check_counts_both_partners(
    config: AppConfig, service: OrderService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hl7_result(ConnectionCheck(False, REASON_NO_RESPONSE), monkeypatch)
    with _client(config, service) as client:
        body = _post(client, "/connection/check").text
    assert 'data-result="2 件のうち 1 件に接続できませんでした。"' in body
    assert 'data-k="ng">失敗</span>' in body


def test_page_script_marks_the_checking_row_and_restores_focus(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        script = client.get("/static/app.js").text
    assert '"htmx:beforeRequest"' in script and "確認中" in script and 'data-k", "check"' in script
    assert 'indexOf("/connections/check")' in script and "announcePageUnreadable" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い（CI の ubuntu には入っている）")
def test_checking_cell_is_restored_when_the_request_is_not_sent() -> None:
    """確認が重なって 204 が返ると、「確認中」にした欄は元に戻る。200 では戻さない（応答が差し替える）."""
    root = pathlib.Path(__file__).resolve().parents[2]
    done = subprocess.run(
        ["node", str(root / "tests/web/connections_checking.js"), str(root / "app/web/static/app.js")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    shown = json.loads(done.stdout)
    assert shown["initial"] == ["未確認0", "未確認1"]
    # 押した行だけ「確認中」になり、204 で元に戻る
    assert shown["checking"] == ["確認中", "未確認1"]
    assert shown["after204"] == ["未確認0", "未確認1"]
    assert shown["after200"] == ["確認中", "未確認1"]


def test_check_connection_opens_and_closes_without_sending() -> None:
    with stub_receiver(lambda text: None) as receiver:
        result = check_connection("127.0.0.1", receiver.port, 2.0)
        time.sleep(0.3)
    assert result == ConnectionCheck(True)
    # 何も送らないので、相手は 1 通も受けていない
    assert receiver.received == []


def test_check_connection_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    refused = check_connection("127.0.0.1", closed_port, 1.0)
    assert refused.ok is False and refused.reason == REASON_REFUSED and refused.detail

    def unresolved(*args: object, **kwargs: object) -> None:
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", unresolved)
    assert check_connection("no-such-host.invalid", 2575, 1.0).reason == REASON_UNKNOWN_HOST
    monkeypatch.undo()

    def timed_out(*args: object, **kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", timed_out)
    assert check_connection("192.0.2.1", 2575, 1.0).reason == REASON_NO_RESPONSE


def test_check_connection_bounds_the_name_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """名前を引く側が答えなくても、timeout 秒で返す（接続の timeout は名前の解決に効かない）."""
    release = threading.Event()

    def stalled(*args: object, **kwargs: object) -> list:
        release.wait(5)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", stalled)
    started = time.monotonic()
    result = check_connection("slow.example", 2575, 0.3)
    elapsed = time.monotonic() - started
    release.set()
    assert result.ok is False and result.reason == REASON_UNKNOWN_HOST and result.detail
    assert elapsed < 2.0


def test_check_connection_shares_one_timeout_across_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    """IPv4・IPv6 の両方に解けても、合わせて timeout 秒まで（アドレスごとに timeout を使い切らない）."""
    infos = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 2575, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 2575)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: infos)
    waits: list[float] = []

    def stall(address: tuple, timeout: float) -> None:
        waits.append(timeout)
        time.sleep(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", stall)
    started = time.monotonic()
    result = check_connection("dual.example", 2575, 0.4)
    elapsed = time.monotonic() - started
    assert result.reason == REASON_NO_RESPONSE
    assert waits and sum(waits) <= 0.4 + 0.05 and elapsed < 1.0


def test_check_connection_reports_an_unconvertible_host_name() -> None:
    """IDNA に直せないホスト名（63 字を超える部分）は、500 にせず「ホスト名を引けません」にする."""
    result = check_connection("a" * 70 + ".example", 2575, 1.0)
    assert result.ok is False and result.reason == REASON_UNKNOWN_HOST and result.detail
