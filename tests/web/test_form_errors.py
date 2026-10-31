"""入力欄の誤り（openspec/specs/order-entry の「入力欄の誤り」）：欄ごとの文・件数の知らせ・novalidate."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.config import AppConfig
from app.services.order_service import OrderService
from app.web.app import FORM_ERRORS_MESSAGE, create_app
from tests.conftest import add_unscheduled_mpps
from tests.web.html_attrs import has_tag
from tests.web.test_order_entry import ENTRY, _client, _post

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "static"


def _alert(page: str) -> str:
    """画面の上の知らせ（#form-errors）の文."""
    match = re.search(
        r'<div id="form-errors"[^>]*><div class="notice" data-k="err" role="alert"><svg [^>]*>.*?</svg><div>([^<]*)</div>', page
    )
    assert match is not None
    return html.unescape(match.group(1))


def _msg(page: str, name: str) -> str:
    """欄の下の誤りの 1 行（.msg）の文。隠れていれば空."""
    match = re.search(rf'<span class="msg" id="error-{name}"( hidden)?><svg [^>]*>.*?</svg><span>([^<]*)</span>', page)
    assert match is not None, name
    return "" if match.group(1) else html.unescape(match.group(2))


def test_forms_are_novalidate_and_checked_by_the_script(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        pages = [client.get(path).text for path in ("/orders/new", "/orders/batch")]
        script = client.get("/static/app.js").text
    for page in pages:
        assert has_tag(page, "form", novalidate=None, **{"data-validate": None})
        assert has_tag(page, "div", id="form-errors", hidden=None)
    # 送るとき、誤りの件数を出して最初の誤りの欄へ焦点を移し、送らない
    assert 'hasAttribute("data-validate")' in script
    assert "controls[0].focus()" in script and "event.preventDefault()" in script
    assert FORM_ERRORS_MESSAGE.replace("{count}", "{count}") in script


def test_required_marks_are_only_the_req_badge(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        pages = [client.get(path).text for path in ("/orders/new", "/orders/batch")]
    for page in pages:
        assert 'aria-required="true"' not in page and "text-danger" not in page


def test_entry_returns_each_error_under_its_field(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "department": "", "date": "2026-13-40"})
    page = response.text
    assert response.status_code == 400
    assert _alert(page) == FORM_ERRORS_MESSAGE.format(count=2)
    assert _msg(page, "department") == "依頼科を選んでください"
    assert _msg(page, "date") == "予定日は YYYY-MM-DD の日付で指定してください"
    assert has_tag(page, "select", name="department", **{"aria-invalid": "true", "aria-describedby": "error-department"})
    assert has_tag(page, "input", name="date", **{"aria-invalid": "true", "aria-describedby": "error-date"})
    # 誤りの無い欄は隠したまま
    assert _msg(page, "modality") == ""
    assert not has_tag(page, "select", name="modality", **{"aria-invalid": "true"})
    assert service.list_orders() == []


def test_entry_error_in_time_and_exam_choices(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "minute": "07", "station": ""})
    page = response.text
    assert _alert(page) == FORM_ERRORS_MESSAGE.format(count=2)
    assert _msg(page, "time") == "予定時刻の分は 15 分ごとにしてください"
    assert _msg(page, "station") == "装置を選んでください"
    assert has_tag(page, "select", name="hour", **{"aria-invalid": "true", "aria-describedby": "error-time"})
    assert has_tag(page, "select", name="station", **{"aria-invalid": "true"})


def test_entry_roster_choice_error_goes_to_the_roster_field(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "roster_patient_id": ""})
    assert _msg(response.text, "roster-patient-id") == "名簿の患者を選んでください"
    assert has_tag(response.text, "select", name="roster_patient_id", **{"aria-invalid": "true"})


def test_error_without_a_field_stays_in_the_top_notice(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "modality": "MR", "station": "MR1号機"})
    page = response.text
    assert response.status_code == 400
    assert _alert(page) == "MR の検査の種類に無いコードです: CT0001"
    assert 'data-count' not in page
    assert not has_tag(page, "select", **{"aria-invalid": "true"})


def test_valid_entry_shows_no_error(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/orders/new").text
    assert 'aria-invalid' not in page and "data-count" not in page


def test_batch_returns_each_error_under_its_field(config: AppConfig, service: OrderService) -> None:
    data = {"count_CT": "-1", "count_MR": "x", "date": "2026-10-21", "hour": "09", "minute": "00", "interval": "15", "patients": "random"}
    with _client(config, service) as client:
        response = _post(client, "/orders/batch", data)
    page = response.text
    assert response.status_code == 400
    assert _alert(page) == FORM_ERRORS_MESSAGE.format(count=2)
    assert _msg(page, "count-CT") == "CT の件数は 0 以上にしてください"
    assert _msg(page, "count-MR") == "MR の件数が数ではありません"
    assert has_tag(page, "input", name="count_CT", **{"aria-invalid": "true", "aria-describedby": "error-count-CT"})


def test_batch_without_counts_marks_the_count_group(config: AppConfig, service: OrderService) -> None:
    data = {"date": "2026-10-21", "hour": "09", "minute": "00", "interval": "15", "patients": "random"}
    with _client(config, service) as client:
        response = _post(client, "/orders/batch", data)
    assert _alert(response.text) == FORM_ERRORS_MESSAGE.format(count=1)
    assert _msg(response.text, "counts") == "どれかのモダリティに 1 以上の件数を入れてください"


def test_reconcile_returns_the_error_under_its_field(config: AppConfig, store) -> None:  # noqa: ANN001
    sop_uid, _ = add_unscheduled_mpps(store)
    service = OrderService(config, store)
    app = create_app(config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url="http://127.0.0.1:8081") as client:
        page = client.get(f"/reconciliation/{sop_uid}").text
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            {"patient": "manual", "patient_id": "", "alphabetic_family": "SATO", "department": "内科"},
        )
        roster = _post(client, f"/reconciliation/{sop_uid}", {"patient": "roster", "roster_patient_id": ""})
    assert has_tag(page, "form", novalidate=None, **{"data-validate": None})
    assert response.status_code == 400
    assert _alert(response.text) == FORM_ERRORS_MESSAGE.format(count=1)
    assert _msg(response.text, "patient-id") == "患者ID を入力してください。"
    assert has_tag(response.text, "input", name="patient_id", **{"aria-invalid": "true", "aria-describedby": "error-patient-id"})
    assert _msg(roster.text, "roster-patient-id") == "名簿の患者を選んでください"


def _run_count_helpers(inputs: list[str]) -> list:
    """画面のスクリプトの件数の数え方と「どれかに 1 以上」の外し方を、仮の form で動かす."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無いので、画面のスクリプトを動かせない")
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    shown = re.search(r"function shownErrorCount.*?\n  }\n", source, re.S)
    clear = re.search(r"function clearCountsError.*?\n  }\n", source, re.S)
    assert shown and clear
    program = shown.group(0) + clear.group(0)
    program += """
var counts = {hidden: false};
var msgs = [counts, {hidden: false}, {hidden: true}];
var inputs = JSON.parse(process.argv[1]).map(function (v) { return {value: v}; });
var form = {
  querySelectorAll: function (selector) {
    if (selector === ".msg:not([hidden])") { return msgs.filter(function (m) { return !m.hidden; }); }
    if (selector === "input[name^=count_]") { return inputs; }
    throw new Error(selector);
  },
  querySelector: function (selector) {
    if (selector === "#error-counts") { return counts; }
    throw new Error(selector);
  },
};
var before = shownErrorCount(form);
var cleared = clearCountsError(form);
console.log(JSON.stringify([before, cleared, counts.hidden, shownErrorCount(form)]));
"""
    result = subprocess.run([node, "-e", program, json.dumps(inputs)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_script_hides_the_counts_error_once_a_count_is_entered() -> None:
    """一括作成の「どれかに 1 以上」は、件数を入れたら消え、画面の上の件数も 1 減る."""
    assert _run_count_helpers(["", "2"]) == [2, True, True, 1]


def test_script_keeps_the_counts_error_while_every_count_is_empty_or_zero() -> None:
    assert _run_count_helpers(["", "0"]) == [2, False, False, 2]


def test_script_counts_the_shown_messages_only() -> None:
    """件数の数え方は 1 つ。aria-invalid ではなく、出ている誤りの文（.msg）の数."""
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "[aria-invalid=true]\").length" not in source
    assert source.count("shownErrorCount(") == 3
