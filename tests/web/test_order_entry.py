"""予約作成と一括作成の画面（openspec/changes/rework-order-entry）の試験."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.services.config import AppConfig, Station
from app.services.order_service import OrderService
from app.services.store import OrderStore
from app.web.app import create_app
from tests.conftest import TODAY

ORIGIN = "http://127.0.0.1:8081"


def _client(config: AppConfig, service: OrderService) -> TestClient:
    return TestClient(create_app(config, password=None, service=service, start_mwl=False), base_url=ORIGIN)


def _post(client: TestClient, path: str, data: dict[str, str]):  # noqa: ANN202
    token = client.app.state.csrf_token  # type: ignore[attr-defined]
    return client.post(
        path, data={"csrf_token": token, **data}, headers={"Origin": ORIGIN}, follow_redirects=False
    )


def _options(page: str, name: str) -> list[str]:
    """`<select name=...>` の選択肢の値."""
    match = re.search(rf'<select name="{name}"[^>]*>(.*?)</select>', page, re.S)
    assert match is not None, name
    return re.findall(r'<option value="([^"]*)"', match.group(1))


def _with_slot_minutes(config: AppConfig, store: OrderStore, minutes: int) -> tuple[AppConfig, OrderService]:
    orders = config.orders.model_copy(update={"slot_minutes": minutes})
    changed = config.model_copy(update={"orders": orders})
    return changed, OrderService(changed, store, today=lambda: TODAY)


def _with_two_ct_stations(config: AppConfig, store: OrderStore) -> tuple[AppConfig, OrderService]:
    ct = config.orders.modalities["CT"].model_copy(
        update={
            "stations": [
                Station(name="CT1号機", ae_title="CT01", station_name="CT01"),
                Station(name="CT2号機", ae_title="CT02", station_name="CT02"),
            ]
        }
    )
    orders = config.orders.model_copy(update={"modalities": {**config.orders.modalities, "CT": ct}})
    changed = config.model_copy(update={"orders": orders})
    return changed, OrderService(changed, store, today=lambda: TODAY)


ENTRY = {
    "patient": "roster",
    "roster_patient_id": "P000002",
    "modality": "CT",
    "procedure": "CT0001",
    "station": "CT1号機",
    "date": "2026-10-21",
    "hour": "10",
    "minute": "30",
    "department": "内科",
    "charset": "utf8",
}


def test_entry_sections_in_order(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/orders/new").text
    assert re.findall(r"<legend>([^<]+)</legend>", page) == ["患者", "検査", "予定", "依頼"]
    assert 'name="seed"' not in page and 'name="count_' not in page and "シード" not in page
    assert '<button type="submit" class="btn btn-primary">登録</button>' in page
    # 名簿の患者（患者 ID・患者氏名・生年月日・性別）と新規（架空）
    assert "名簿から選ぶ" in page and "新規（架空）" in page
    assert "P000002 佐藤 由紀（サトウ ユキ） 1992-08-25 F" in page
    assert _options(page, "modality") == list(config.orders.modalities)
    assert _options(page, "procedure") == ["CT0001", "CT0002", "CT0003", "CT0004"]
    assert _options(page, "station") == ["CT1号機"]
    assert _options(page, "minute") == ["00", "15", "30", "45"]
    assert _options(page, "hour") == [f"{h:02d}" for h in range(24)]
    # 依頼科は必ず1つ選ぶ（「ランダム」などの空の選択肢を出さない）
    assert _options(page, "department") == config.orders.departments


def test_register_one_order(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "department": "整形外科"})
    orders = service.list_orders()
    assert len(orders) == 1
    order = orders[0]
    assert response.status_code == 303
    assert response.headers["location"] == f"/orders/{order.accession_number}"
    assert order.patient.patient_id == "P000002"
    assert order.procedure.name == "頭部 CT 単純"
    assert order.scheduled_station_label == "CT1号機"
    assert (order.scheduled_date, order.scheduled_time) == ("20261021", "103000")
    assert order.requesting_service == "整形外科"


def test_register_new_fictitious_patient(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "patient": "new", "roster_patient_id": ""})
    assert response.status_code == 303
    order = service.list_orders()[0]
    assert order.patient.patient_id.startswith(config.orders.patient_id_prefix)


def test_new_patient_ignores_roster_choice_whether_or_not_it_is_sent(
    config: AppConfig, service: OrderService
) -> None:
    # 画面は「新規（架空）」の間、名簿の患者の選択肢を無効にする。無効な欄はブラウザが送らない。
    # 送られても送られなくても、新規は名簿の患者を使わない
    with _client(config, service) as client:
        omitted = {key: value for key, value in ENTRY.items() if key != "roster_patient_id"}
        assert _post(client, "/orders", {**omitted, "patient": "new"}).status_code == 303
        assert _post(client, "/orders", {**ENTRY, "patient": "new"}).status_code == 303
    patients = {order.patient.patient_id for order in service.list_orders()}
    assert len(patients) == 2 and "P000002" not in patients


def test_roster_select_follows_the_patient_choice(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/orders/new").text
        script = client.get("/static/app.js").text
    assert re.search(r'<select name="roster_patient_id" data-roster-select>', page)
    # 患者の選択が変わったとき、読み込んだとき、戻るボタンで戻ったときに、無効かどうかを合わせる
    assert "input[name=patient][value=new]" in script
    assert 'name === "patient"' in script and '"pageshow", syncRosterSelect' in script


def test_entry_rejects_mismatched_choices(config: AppConfig, service: OrderService) -> None:
    cases = {
        "MR の検査の種類に無いコードです: CT0001": {"modality": "MR", "station": "MR1号機"},
        "CT の台帳に無い装置です: MR1号機": {"station": "MR1号機"},
        "予定時刻の分は 15 分ごとにしてください": {"minute": "07"},
        "依頼科を選んでください": {"department": ""},
        "名簿に無い患者 ID です: P999999": {"roster_patient_id": "P999999"},
        "予定日は YYYY-MM-DD の日付で指定してください": {"date": "2026-13-40"},
    }
    with _client(config, service) as client:
        for message, change in cases.items():
            response = _post(client, "/orders", {**ENTRY, **change})
            assert response.status_code == 400, message
            assert message in response.text, message
    assert service.list_orders() == []


def test_exam_options_follow_modality(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        options = client.get("/orders/new/exam?modality=MR")
        unknown = client.get("/orders/new/exam?modality=XX")
    assert options.status_code == 200
    assert _options(options.text, "procedure") == ["MR0001", "MR0002", "MR0003"]
    assert _options(options.text, "station") == ["MR1号機"]
    assert 'id="exam-options"' in options.text
    assert unknown.status_code == 400


def test_entry_minutes_follow_slot_setting(config: AppConfig, store: OrderStore) -> None:
    changed, service = _with_slot_minutes(config, store, 1)
    with _client(changed, service) as client:
        page = client.get("/orders/new").text
    assert _options(page, "minute") == [f"{m:02d}" for m in range(60)]


def test_entry_without_roster(config: AppConfig, store: OrderStore) -> None:
    orders = config.orders.model_copy(update={"roster_path": "/nonexistent/roster.yaml"})
    changed = config.model_copy(update={"orders": orders})
    service = OrderService(changed, store, today=lambda: TODAY)
    with _client(changed, service) as client:
        page = client.get("/orders/new").text
    assert "名簿を読めません" in page
    assert re.search(r'value="roster"[^>]*disabled', page)
    assert re.search(r'value="new" required checked', page)


def test_roster_failure_after_choosing_does_not_switch_to_new(config: AppConfig, store: OrderStore) -> None:
    orders = config.orders.model_copy(update={"roster_path": "/nonexistent/roster.yaml"})
    changed = config.model_copy(update={"orders": orders})
    service = OrderService(changed, store, today=lambda: TODAY)
    with _client(changed, service) as client:
        response = _post(client, "/orders", ENTRY)
    assert response.status_code == 400
    # 名簿を選んで送った後に名簿が読めなくなったら、どちらの患者の選択肢も選ばれていない
    assert not re.search(r'name="patient" value="[a-z]+" required[^>]* checked', response.text)
    assert service.list_orders() == []


def test_removed_roster_patient_is_not_replaced(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        response = _post(client, "/orders", {**ENTRY, "roster_patient_id": "P999999"})
        again = _post(client, "/orders", {**ENTRY, "roster_patient_id": ""})
    assert response.status_code == 400 and "名簿に無い患者 ID です: P999999" in response.text
    # 先頭の患者に黙って替えず、空の選択肢を選んだ形で出す
    assert _options(response.text, "roster_patient_id")[0] == ""
    assert '<option value="" selected>選択してください</option>' in response.text
    assert again.status_code == 400 and "名簿の患者を選んでください" in again.text
    assert service.list_orders() == []


def test_rejected_form_post_shows_page(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        stale = client.post(
            "/orders", data={**ENTRY, "csrf_token": "stale"}, headers={"Origin": ORIGIN}
        )
        htmx = client.post(
            "/orders/x/status",
            data={"status": "completed"},
            headers={"Origin": ORIGIN, "HX-Request": "true", "X-CSRF-Token": "stale"},
        )
    assert stale.status_code == 403
    assert "送信を受け付けませんでした。画面を開き直して、もう一度操作してください。" in stale.text
    assert '<a href="/orders">予約一覧へ</a>' in stale.text
    # htmx の要求は今までどおり（画面の上のエラーは app.js が出す）
    assert htmx.status_code == 403 and "送信を受け付けませんでした" not in htmx.text


def test_batch_page_words(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        page = client.get("/orders/batch").text
    assert "<title>一括作成 - ris-emulator</title>" in page
    assert re.findall(r"<legend>([^<]+)</legend>", page)[1:] == ["予定", "患者", "依頼"]
    assert "新規（架空）" in page and "名簿から無作為に" in page
    assert _options(page, "department")[0] == "" and ">ランダム</option>" in page
    for word in ("順に使う", "乱数で作る", "乱数で選ぶ", "名簿から選ぶ", "シード"):
        assert word not in page, word
    assert 'name="seed"' not in page
    assert _options(page, "interval") == ["1", "5", "10", "15", "20", "30", "60"]
    assert _options(page, "minute") == ["00", "15", "30", "45"]
    # 既定の台帳は1台なので、装置の選択肢を出さない
    assert 'name="station_CT"' not in page


def test_batch_minutes_follow_interval(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        one = client.get("/orders/batch/minutes?interval=1&minute=07").text
        hour = client.get("/orders/batch/minutes?interval=60&minute=30").text
        kept = client.get("/orders/batch/minutes?interval=30&minute=30").text
    assert _options(one, "minute") == [f"{m:02d}" for m in range(60)]
    assert 'value="07" selected' in one
    assert _options(hour, "minute") == ["00"]
    assert 'value="30" selected' in kept


def test_batch_rejects_minutes_off_interval(config: AppConfig, service: OrderService) -> None:
    base = {"count_CT": "2", "date": "2026-10-21", "hour": "09", "patients": "random"}
    with _client(config, service) as client:
        off = _post(client, "/orders/batch", {**base, "minute": "10", "interval": "15"})
        odd = _post(client, "/orders/batch", {**base, "minute": "00", "interval": "45"})
        ok = _post(client, "/orders/batch", {**base, "minute": "07", "interval": "1"})
    assert off.status_code == 400 and "開始時刻の分は 15 分ごとにしてください" in off.text
    assert odd.status_code == 400 and "間隔は 1・5・10・15・20・30・60 分から選んでください" in odd.text
    assert ok.status_code == 303
    assert [o.scheduled_time for o in service.list_orders()] == ["090700", "090800"]


def test_batch_station_choice_with_two_stations(config: AppConfig, store: OrderStore) -> None:
    changed, service = _with_two_ct_stations(config, store)
    base = {"date": "2026-10-21", "hour": "09", "minute": "00", "interval": "15", "patients": "random"}
    with _client(changed, service) as client:
        page = client.get("/orders/batch").text
        _post(client, "/orders/batch", {**base, "count_CT": "3"})
    assert _options(page, "station_CT") == ["", "CT1号機", "CT2号機"]
    assert '<option value="">全装置に振り分け</option>' in page
    assert 'name="station_MR"' not in page
    # 「全装置に振り分け」（既定）では台帳の順に使う
    assert [o.scheduled_station_ae_title for o in service.list_orders()] == ["CT01", "CT02", "CT01"]


def test_entry_station_default_is_first(config: AppConfig, store: OrderStore) -> None:
    changed, service = _with_two_ct_stations(config, store)
    with _client(changed, service) as client:
        page = client.get("/orders/new").text
    assert _options(page, "station") == ["CT1号機", "CT2号機"]
    # 選ばれた選択肢が無ければ、ブラウザは先頭（台帳の1台目）を選ぶ
    assert "selected" not in re.search(r'<select name="station">(.*?)</select>', page, re.S).group(1)  # type: ignore[union-attr]


def test_submit_buttons_are_guarded(config: AppConfig, service: OrderService) -> None:
    with _client(config, service) as client:
        script = client.get("/static/app.js").text
        listing = client.get("/orders").text
    assert 'addEventListener("submit"' in script and "disabled = true" in script
    # htmx の要求が 401 なら読み直して、ブラウザに認証を求めさせる
    assert "status === 401" in script and "location.reload()" in script
    # 一覧の主の操作（表示）を、ほかのボタン（前日・本日・翌日）と見分けられるようにする
    assert '<button type="submit" class="btn btn-primary">表示</button>' in listing
    # 0件の文と予約作成のリンクを分ける
    assert '<p class="empty">条件に合う予約はありません。</p>' in listing
