"""照合の生年月日の欄：西暦と和暦の入力、欄の下の読み取り結果（docs/spec/03_web_cli.md）."""

from __future__ import annotations

import html
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.wareki import BIRTH_FORMAT_MESSAGE, BIRTH_FUTURE_MESSAGE
from app.services.config import AppConfig
from app.services.order_service import OrderService
from app.services.store import OrderStore
from app.web.app import create_app
from tests.conftest import NOW, add_unscheduled_mpps

ORIGIN = "http://127.0.0.1:8081"
OPENED = date(2026, 10, 29)  # 画面を開いた日（サーバーの今日）。MPPS の開始日は 2026/10/21
STUDY_DAY = "20261021"
STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
HEISEI_AFTER = "生年月日が平成の範囲にありません。平成は 2019/04/30 までです。令和1年は 2019/05/01 からです。"


@contextmanager
def _client(config: AppConfig, store: OrderStore) -> Iterator[tuple[TestClient, OrderService]]:
    service = OrderService(config, store, today=lambda: OPENED, now=lambda: NOW)
    app = create_app(config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, service


def _post(client: TestClient, path: str, **data: str):  # noqa: ANN202
    return client.post(
        path,
        data={"csrf_token": client.app.state.csrf_token, **data},  # type: ignore[attr-defined]
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )


def _manual(birth_date: str) -> dict[str, str]:
    return {"patient": "manual", "patient_id": "X1", "alphabetic_family": "SATO", "birth_date": birth_date}


def _confirm_fields(page: str) -> dict[str, str]:
    form = page.split('id="dlg-reconcile-form">', 1)[1].split("</form>", 1)[0]
    fields = {}
    for part in form.split('<input type="hidden" name="')[1:]:
        name, rest = part.split('" value="', 1)
        fields[html.unescape(name)] = html.unescape(rest.split('">', 1)[0])
    return fields


def _birth_field(page: str) -> str:
    """照合の画面の生年月日の欄（label の中）."""
    end = page.index('name="birth_date"')
    return page[page.rindex("<label", 0, end) : page.index("</label>", end)]


def _hint(client: TestClient, value: str, on: str = STUDY_DAY) -> str:
    response = client.get("/birth-date/hint", params={"birth_date": value, "on": on})
    assert response.status_code == 200
    return html.unescape(response.text)


def test_birth_field_is_one_text_field_tied_to_the_hint_and_the_message(
    config: AppConfig, store: OrderStore
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        field = _birth_field(client.get(f"/reconciliation/{sop_uid}").text)
    assert 'type="text"' in field and 'inputmode="text"' in field and 'autocomplete="off"' in field
    assert 'type="date"' not in field
    assert 'aria-describedby="hint-birth-date error-birth-date"' in field
    assert "aria-live" not in field
    # 年齢は照合の検査日（MPPS の開始日）で数える
    assert f'hx-get="/birth-date/hint?on={STUDY_DAY}"' in field
    assert 'hx-trigger="input changed delay:250ms"' in field
    # 空のときは .hint も .msg も出さない
    assert '<span class="hint" id="hint-birth-date" hidden></span>' in field
    assert 'id="error-birth-date" hidden>' in field


@pytest.mark.parametrize("value", ["S50/05/14", "昭和50年5月14日", "1975/5/14", "ｓ50/5/14"])
def test_hint_shows_the_reading(config: AppConfig, store: OrderStore, value: str) -> None:
    with _client(config, store) as (client, _):
        fragment = _hint(client, value)
    assert fragment.strip() == '<span class="hint" id="hint-birth-date">1975/05/14（昭50・51歳）</span>'


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("S50-05-14", BIRTH_FORMAT_MESSAGE),
        ("H31/05/01", HEISEI_AFTER),
        ("2026/10/30", BIRTH_FUTURE_MESSAGE),
    ],
)
def test_hint_is_empty_and_carries_the_message_when_unreadable(
    config: AppConfig, store: OrderStore, value: str, message: str
) -> None:
    with _client(config, store) as (client, _):
        fragment = _hint(client, value)
    assert fragment.strip() == f'<span class="hint" id="hint-birth-date" data-error="{message}" hidden></span>'


def test_hint_counts_the_age_on_the_study_day(config: AppConfig, store: OrderStore) -> None:
    """1975/10/22 生まれ：検査日 2026/10/21 は誕生日の前日で 50 歳、開いた日 2026/10/29 では 51 歳."""
    with _client(config, store) as (client, _):
        assert "1975/10/22（昭50・50歳）" in _hint(client, "S50/10/22")
        assert "1975/10/22（昭50・51歳）" in _hint(client, "S50/10/22", on="")
        # 数える日より後で今日以前の生年月日は、年齢を出さない
        assert "2026/10/25（令8）<" in _hint(client, "R8/10/25")


def test_empty_hint_shows_nothing(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, _):
        assert _hint(client, "").strip() == '<span class="hint" id="hint-birth-date" hidden></span>'


@pytest.mark.parametrize("value", ["S50/05/14", "昭和50年5月14日"])
def test_wareki_birth_date_is_saved_in_the_western_calendar(
    config: AppConfig, store: OrderStore, value: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    path = f"/reconciliation/{sop_uid}"
    with _client(config, store) as (client, service):
        first = _post(client, path, **_manual(value), procedure="CT0001")
        assert first.status_code == 200
        # 確認の窓は西暦で出し、窓が送り直す値も読み取った西暦にする
        fields = _confirm_fields(first.text)
        assert "1975/05/14" in first.text
        response = client.post(path, data=fields, headers={"Origin": ORIGIN}, follow_redirects=False)
        assert response.status_code == 303
        assert service.list_orders()[0].patient.birth_date == "19750514"


@pytest.mark.parametrize("value", ["1975-05-14", "1975-5-14", "19750514"])
def test_legacy_birth_date_forms_are_still_accepted(
    config: AppConfig, store: OrderStore, value: str
) -> None:
    """画面の外から送る呼び出しのため、照合の受け口は旧い形（ハイフン・8 桁）も受ける."""
    sop_uid, _ = add_unscheduled_mpps(store)
    path = f"/reconciliation/{sop_uid}"
    with _client(config, store) as (client, service):
        assert "1975/05/14（昭50・51歳）" in _hint(client, value)
        first = _post(client, path, **_manual(value), procedure="CT0001")
        assert first.status_code == 200
        response = client.post(
            path, data=_confirm_fields(first.text), headers={"Origin": ORIGIN}, follow_redirects=False
        )
        assert response.status_code == 303
        assert service.list_orders()[0].patient.birth_date == "19750514"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("S50-05-14", BIRTH_FORMAT_MESSAGE),
        ("H31/05/01", HEISEI_AFTER),
        ("2026/10/30", BIRTH_FUTURE_MESSAGE),
    ],
)
def test_server_refuses_unreadable_birth_dates_with_the_same_message(
    config: AppConfig, store: OrderStore, value: str, message: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        response = _post(client, f"/reconciliation/{sop_uid}", **_manual(value))
        assert service.count_orders() == 0
    page = html.unescape(response.text)
    assert response.status_code == 400
    # 画面の上の知らせ（role="alert"）の 1 つに文を出す
    alerts = [part.split("</div>", 1)[0] for part in page.split('role="alert"')[1:]]
    assert any(message in alert for alert in alerts), alerts
    # 欄には入れた値を残し、欄の下にも同じ文を出す
    field = _birth_field(page)
    assert f'value="{value}"' in field
    assert 'aria-invalid="true"' in field and "data-unreadable" in field
    assert '<span class="msg" id="error-birth-date"><svg' in field and f"<span>{message}</span>" in field


def test_script_takes_the_reading_from_the_server() -> None:
    """画面のスクリプトは元号の表を持たず、サーバーの読み取り結果（data-error）で欄を確かめる."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in ("htmx:afterSettle", "data-unreadable", "data-error", 'described(input, "msg")'):
        assert marker in script, marker
    for era in ("令和", "平成", "昭和", "1989", "2019"):
        assert era not in script, era
