"""照合の画面の試験（docs/spec/07_reconciliation.md 5 章）。HL7 の受け手は試験用のスタブ."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.services.config import AppConfig
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore
from app.web.app import create_app
from tests.conftest import NOW, TODAY, add_unscheduled_mpps
from tests.hl7.stub import ack, stub_receiver
from tests.web.html_attrs import has_tag

ORIGIN = "http://127.0.0.1:8081"
ROSTER_ID = "P000001"


@contextmanager
def _client(
    config: AppConfig, store: OrderStore, port: int = 1
) -> Iterator[tuple[TestClient, OrderService]]:
    hl7 = config.hl7.model_copy(update={"port": port, "timeout_seconds": 2.0})
    service = OrderService(
        config.model_copy(update={"hl7": hl7}), store, today=lambda: TODAY, now=lambda: NOW
    )
    app = create_app(service.config, password=None, service=service, start_mwl=False)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, service


def _post(client: TestClient, path: str, **data: str):  # noqa: ANN202
    return client.post(
        path,
        data={"csrf_token": client.app.state.csrf_token, **data},  # type: ignore[attr-defined]
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )


def _dialog(page: str) -> str:
    """照合の確認の窓の HTML."""
    assert '<dialog id="dlg-reconcile"' in page, page[:300]
    return page.split('<dialog id="dlg-reconcile"', 1)[1].split("</dialog>", 1)[0]


def _confirm_fields(page: str) -> dict[str, str]:
    """確認の窓の「照合・送信する」が送る値."""
    form = _dialog(page).split('id="dlg-reconcile-form">', 1)[1].split("</form>", 1)[0]
    return {
        html.unescape(name): html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]*)" value="([^"]*)">', form)
    }


def _reconcile(client: TestClient, path: str, **data: str):  # noqa: ANN202
    """照合の画面の流れ：「照合・送信」で確認の窓を出し、窓の「照合・送信する」で確定する."""
    first = _post(client, path, **data)
    if first.status_code != 200:
        return first
    return client.post(
        path, data=_confirm_fields(first.text), headers={"Origin": ORIGIN}, follow_redirects=False
    )


def _roster(**extra: str) -> dict[str, str]:
    return {"patient": "roster", "roster_patient_id": ROSTER_ID, **extra}


def _accept(text: str) -> bytes:
    return ack("AA", text)


def test_empty_list(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, _):
        page = client.get("/reconciliation")
    assert page.status_code == 200
    assert "<h1>未照合</h1>" in page.text and "未照合の撮影はありません。" in page.text
    assert "<title>未照合 - ris-emulator</title>" in page.text
    # 空の状態：1 行目に事実、2 行目に次の手。表の見出しの行は出したままにする
    assert "<b>未照合の撮影はありません。</b>" in page.text
    assert "<span>予約の無い撮影をモダリティから受けると、ここに出ます。</span>" in page.text
    assert "<thead>" in page.text and '<b class="count-n">0</b>' in page.text


def test_list_shows_mpps_state_as_marks(config: AppConfig, store: OrderStore) -> None:
    add_unscheduled_mpps(store)
    add_unscheduled_mpps(store, patient_id="ER2026102401", status="COMPLETED")
    with _client(config, store) as (client, _):
        page = client.get("/reconciliation").text.split("</header>")[1]
    assert '<b class="count-n">2</b>' in page
    marks = re.findall(r'<span class="st" data-k="([a-z]+)">([^<]+)</span>', page)
    assert sorted(marks) == [("done", "完了"), ("run", "実施中")]
    assert "IN PROGRESS" not in page and "COMPLETED" not in page
    # 行の中のボタンは副（高さ 24px）で、UID は省略して全文を title に持つ
    assert 'class="btn btn-row">照合</a>' in page and 'class="mono uid-c" title="' in page


def test_list_shows_unreconciled_only_and_links_to_the_form(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        scheduled = service.create_orders(
            OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1)
        )[0]
        store.create_mpps("1.2.3", [(scheduled.accession_number, scheduled.scheduled_procedure_step_id)], {})
        page = client.get("/reconciliation").text
    assert "ER2026102400" in page and study_uid in page and "不明 男性" in page
    assert page.count("<tbody>") == 1 and page.count("<tr>") == 2  # 見出しと1件
    assert f'href="/reconciliation/{sop_uid}"' in page
    headers = [h.strip() for h in re.findall(r"<th[^>]*>(?:<span[^>]*>)?([^<]*)", page) if h.strip()]
    assert headers == [
        "受けた日時", "状態", "患者ID", "氏名", "生年月日・性別",
        "モダリティ", "予定の AEタイトル", "Study Instance UID", "操作",
    ]  # fmt: skip


def test_form_shows_the_shooting_and_choices(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        page = client.get(f"/reconciliation/{sop_uid}").text
    assert study_uid in page and "UNKNOWN^MALE=不明^男性=フメイ^ダンセイ" in page
    assert f'<option value="{ROSTER_ID}"' in page
    assert re.findall(r'<option value="(CT\d{4})"', page) == ["CT0001", "CT0002", "CT0003", "CT0004"]
    assert '<option value="救急科" selected>' in page
    assert "照合・送信</button>" in page
    assert f'action="/reconciliation/{sop_uid}"' in page


def test_unknown_mpps_is_404(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, _):
        assert client.get("/reconciliation/9.9.9").status_code == 404
        assert _post(client, "/reconciliation/9.9.9", **_roster()).status_code == 404
        assert _post(client, "/orders/RE000/hl7/resend").status_code == 404


def test_form_says_why_it_cannot_reconcile(config: AppConfig, store: OrderStore) -> None:
    no_id, _ = add_unscheduled_mpps(store, patient_id="")
    unknown_modality, _ = add_unscheduled_mpps(store, modality="XA")
    with _client(config, store) as (client, _):
        first = client.get(f"/reconciliation/{no_id}").text
        second = client.get(f"/reconciliation/{unknown_modality}").text
    assert "仮の患者ID がありません" in first and "<form" not in first
    assert "モダリティ XA が設定に無い" in second and "<form" not in second


def test_reconcile_with_roster_patient_sends_and_shows_the_result(config: AppConfig, store: OrderStore) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        response = _reconcile(
            client, f"/reconciliation/{sop_uid}", **_roster(procedure="CT0002", department="外科")
        )
        assert response.status_code == 303
        location = response.headers["location"]
        detail = client.get(location).text
        listing = client.get("/reconciliation").text
    assert receiver.types == ["ADT^A40", "ORM^O01"]
    accession = location.rsplit("/", 1)[1]
    order = service.get(accession)
    assert order.study_instance_uid == study_uid and order.patient.patient_id == ROSTER_ID
    assert (order.procedure.code, order.requesting_service) == ("CT0002", "外科")
    assert "<h2>HL7 送信</h2>" in detail
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", detail) == ["送信完了", "送信完了"]
    assert "<dt>照合前の患者ID</dt><dd class=\"mono\">ER2026102400</dd>" in detail
    assert "UNKNOWN^MALE=不明^男性=フメイ^ダンセイ" in detail
    assert "再送信" not in detail
    assert "未照合の撮影はありません。" in listing


def test_reconcile_with_typed_patient(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        response = _reconcile(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id="X0001",
            alphabetic_family="SATO",
            alphabetic_given="JIRO",
            ideographic_family="佐藤",
            ideographic_given="次郎",
            phonetic_family="",
            phonetic_given="",
            birth_date="1975-04-05",
            sex="M",
            procedure="CT0001",
            department="救急科",
        )
        assert response.status_code == 303
        order = service.get(response.headers["location"].rsplit("/", 1)[1])
    patient = order.patient
    assert (patient.patient_id, patient.birth_date, patient.sex) == ("X0001", "19750405", "M")
    assert patient.name.to_dicom() == "SATO^JIRO=佐藤^次郎"
    assert "PID|1||X0001^^^RIS_EMU^PI||SATO^JIRO^^^^^L^A~佐藤^次郎^^^^^L^I" in receiver.received[0]


def test_input_errors_are_shown_and_nothing_is_created(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    cases = [
        ({}, "患者を、名簿から選ぶか入力するかを選んでください"),
        ({"patient": "roster", "roster_patient_id": ""}, "名簿の患者を選んでください"),
        ({"patient": "roster", "roster_patient_id": "NOPE"}, "名簿に無い患者ID です"),
        ({"patient": "manual", "patient_id": ""}, "患者ID を入力してください"),
        ({"patient": "manual", "patient_id": "X1"}, "氏名を入力してください"),
        (
            {"patient": "manual", "patient_id": "X1", "alphabetic_family": "A", "birth_date": "1975-13-45"},
            "生年月日",
        ),
        (
            {"patient": "manual", "patient_id": "X^1", "alphabetic_family": "A"},
            "患者の値を受け付けられません",
        ),
        (_roster(procedure="CT9999"), "CT9999"),
    ]
    with _client(config, store) as (client, service):
        for data, message in cases:
            response = _post(client, f"/reconciliation/{sop_uid}", **data)
            assert response.status_code == 400, (data, response.text[:200])
            assert message in response.text, data
            assert 'role="alert"' in response.text
        assert service.count_orders() == 0
        assert len(service.store.list_unlinked_mpps()) == 1


def test_values_are_kept_when_the_form_is_shown_again(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id="X0001",
            alphabetic_family="SATO",
            birth_date="1975-13-45",
            department="外科",
        )
    page = response.text
    assert response.status_code == 400
    assert 'value="X0001"' in page and 'value="SATO"' in page and 'value="1975-13-45"' in page
    assert '<option value="外科" selected>' in page


def test_second_reconcile_is_refused(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        accession = _reconcile(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        again = _post(client, f"/reconciliation/{sop_uid}", **_roster())
        page = client.get(f"/reconciliation/{sop_uid}")
        assert service.count_orders() == 1
    assert again.status_code == 409 and "すでに予約に結び付いています" in again.text
    assert f'<a href="{accession}"' in again.text and "<form" not in again.text
    assert "<form" not in page.text and f'<a href="{accession}"' in page.text
    assert len(receiver.received) == 2


def test_rejected_message_is_shown_and_can_be_sent_again(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    answers = iter(["AE", "AA", "AA"])
    with stub_receiver(lambda text: ack(next(answers), text, "unknown patient")) as receiver, _client(
        config, store, receiver.port
    ) as (client, _):
        location = _reconcile(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        before = client.get(location).text
        resend = _post(client, f"{location}/hl7/resend")
        after = client.get(location).text
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", before) == ["拒否", "送信待ち"]
    assert "unknown patient" in before and "<td class=\"mono\">AE</td>" in before
    assert 'action="' + location + '/hl7/resend"' in before and "再送信</button>" in before
    assert resend.status_code == 303 and resend.headers["location"] == location
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", after) == ["送信完了", "送信完了"]
    assert "再送信" not in after
    assert receiver.received[0] == receiver.received[1]


def test_unreachable_receiver_shows_failure(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store, port=1) as (client, _):
        location = _reconcile(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        page = client.get(location).text
    assert re.findall(r"<td>(送信完了|送信待ち|拒否|送信失敗)</td>", page) == ["送信失敗", "送信待ち"]
    assert "再送信</button>" in page


def test_post_without_csrf_token_is_refused(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        response = client.post(
            f"/reconciliation/{sop_uid}", data=_roster(), headers={"Origin": ORIGIN}
        )
        assert response.status_code == 403
        assert service.count_orders() == 0


def test_ordinary_order_has_no_hl7_section(config: AppConfig, store: OrderStore) -> None:
    with _client(config, store) as (client, service):
        order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
        page = client.get(f"/orders/{order.accession_number}").text
    assert "HL7 送信" not in page and "照合前" not in page


def test_detail_terms_for_reconciled_order(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, _):
        location = _reconcile(client, f"/reconciliation/{sop_uid}", **_roster()).headers["location"]
        page = client.get(location).text
    items = set(re.findall(r"<dt>([^<]+)</dt>", page))
    assert {"照合前の患者ID", "照合前の氏名"} <= items
    # 画面の言葉の決まり（openspec/specs/screen-terms/spec.md）で外した言い方が出ない
    assert not [w for w in ("患者 ID", "患者氏名", "AE タイトル", "頁", "既定") if w in page]
    assert re.findall(r"<th>([^<]+)</th>", page.split("<h2>HL7 送信</h2>")[1].split("</thead>")[0]) == [
        "メッセージ", "状態", "ACK", "詳細", "送信日時", "回数",
    ]  # fmt: skip


def test_cancel_reconciled_order_shows_ca(config, store):
    uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver:
        with _client(config, store, receiver.port) as (client, _):
            response = _reconcile(client, f"/reconciliation/{uid}", **_roster())
            accession = store.get_mpps(uid).accession_numbers[0]
            # 確認の窓を通らない取消は、窓（ORM の CA を送ると書いたもの）を開いた詳細を出して止める
            unconfirmed = _post(client, f"/orders/{accession}/status", status="cancelled")
            assert unconfirmed.status_code == 200 and len(receiver.received) == 2
            dialog = unconfirmed.text.split('<dialog id="dlg-status-cancelled"', 1)[1].split("</dialog>")[0]
            assert " open" in dialog.split(">", 1)[0] and "ORM^O01（CA）" in dialog
            response = _post(client, f"/orders/{accession}/status", status="cancelled", confirmed="1")
            assert response.status_code == 303
            page = client.get(response.headers["location"])
            assert "ORM^O01（CA）" in page.text
    assert "\rORC|CA|" in receiver.received[-1]


def test_reconcile_screen_follows_screen_type_c(config: AppConfig, store: OrderStore) -> None:
    """パンくず → 見出し → 患者バナー（仮の患者）→ 区画 → 操作の行。MPPS の状態は札で出す."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        page = client.get(f"/reconciliation/{sop_uid}").text
    order = [
        page.index('<ol class="crumbs">'),
        page.index('<div class="pagehead"><h1>照合</h1></div>'),
        page.index('<section class="banner" aria-label="仮の患者">'),
        page.index('<h2 class="sec-title">受けた撮影</h2>'),
        page.index("<legend>正式な患者</legend>"),
        page.index("<legend>検査</legend>"),
        page.index('<div class="formbar">'),
    ]
    assert order == sorted(order)
    banner = page.split('<section class="banner"', 1)[1].split("</section>", 1)[0]
    assert '<span class="st" data-k="run">実施中</span>' in banner and "ER2026102400" in banner
    assert "IN PROGRESS" not in page
    bar = page.split('<div class="formbar">')[1].split("</div>")[0]
    assert re.findall(r'<(?:a|button)[^>]*class="([^"]+)"[^>]*>([^<]+)<', bar) == [
        ("btn", "キャンセル"),
        ("btn btn-primary", "照合・送信"),
    ]
    # 確認の窓は「照合・送信」を押すまで出さない
    assert "<dialog" not in page


def _rows(dialog: str) -> list[tuple[str, ...]]:
    """確認の窓の比べる表の行（項目と各列の値。違う行には末尾に「違う」）."""
    body = dialog.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [
        tuple(html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row))
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
    ]


def test_reconcile_shows_the_confirm_dialog_and_sends_nothing(config: AppConfig, store: OrderStore) -> None:
    """「照合・送信」は確認の窓を出すだけ。窓に仮の患者と正式な患者を並べ、送る HL7 と送り先を書く."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        response = _post(client, f"/reconciliation/{sop_uid}", **_roster())
        assert service.count_orders() == 0 and len(service.store.list_unlinked_mpps()) == 1
    assert receiver.received == []
    assert response.status_code == 200
    dialog = _dialog(response.text)
    assert 'aria-labelledby="dlg-reconcile-title"' in dialog and " open" in dialog.split(">", 1)[0]
    title = re.search(r'<h2 id="dlg-reconcile-title"[^>]*>([^<]+)</h2>', dialog).group(1)
    assert title == "不明 男性（ER2026102400）を 田中 博（P000001）に照合しますか？"
    assert _rows(dialog) == [
        ("患者ID", "ER2026102400", "P000001", "違う"),
        ("氏名（漢字）", "不明 男性", "田中 博", "違う"),
        ("氏名（かな）", "フメイ ダンセイ", "タナカ ヒロシ", "違う"),
        ("氏名（英字）", "UNKNOWN MALE", "TANAKA HIROSHI", "違う"),
        ("生年月日", "", "1998-03-12", "違う"),
        ("性別", "M", "M", ""),
        ("受付番号", "なし", "照合で新しく付ける", ""),
    ]
    assert re.findall(r'<li><span class="mono">([^<]+)</span> ([^<]+)</li>', dialog) == [
        ("ADT^A40", "患者の統合"),
        ("ORM^O01", "予約"),
    ]
    assert f"予約（頭部 CT 単純・救急科）を作り、PACS（127.0.0.1:{receiver.port}）へ次の HL7 を順に送ります" in dialog
    assert "送った患者の統合は、この画面から取り消せません。" in dialog
    # キャンセルを左（初めのフォーカス）、実行を右
    bar = dialog.split('<div class="ft">', 1)[1]
    assert re.findall(r"<button[^>]*>([^<]+)</button>", bar) == ["キャンセル", "照合・送信する"]
    assert '<form method="dialog"><button type="submit" class="btn" autofocus>キャンセル</button>' in bar
    assert 'form="dlg-reconcile-form" class="btn btn-primary">照合・送信する' in bar
    fields = _confirm_fields(response.text)
    assert fields["roster_patient_id"] == ROSTER_ID and len(fields["confirmed_key"]) == 64
    assert "csrf_token" in fields


def test_confirm_dialog_for_an_update_says_a08(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id="ER2026102400",
            alphabetic_family="SATO",
            alphabetic_given="JIRO",
            sex="M",
        )
    dialog = _dialog(response.text)
    assert re.findall(r'<li><span class="mono">([^<]+)</span> ([^<]+)</li>', dialog) == [
        ("ADT^A08", "患者の更新"),
        ("ORM^O01", "予約"),
    ]
    assert "取り消せません" not in dialog
    assert _rows(dialog)[0] == ("患者ID", "ER2026102400", "ER2026102400", "")


def test_confirm_with_a_stale_key_shows_the_dialog_again(config: AppConfig, store: OrderStore) -> None:
    """確かめた後に撮影の値が変わったら（N-SET）、送らずに窓を出し直す."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with stub_receiver(_accept) as receiver, _client(config, store, receiver.port) as (client, service):
        fields = _confirm_fields(_post(client, f"/reconciliation/{sop_uid}", **_roster()).text)
        store.update_mpps(sop_uid, None, {"PatientID": {"vr": "LO", "Value": ["ER2026102499"]}})
        response = client.post(
            f"/reconciliation/{sop_uid}", data=fields, headers={"Origin": ORIGIN}, follow_redirects=False
        )
        assert service.count_orders() == 0
        forged = _post(client, f"/reconciliation/{sop_uid}", **_roster(confirmed_key="0" * 64))
        assert service.count_orders() == 0
    assert receiver.received == []
    for page in (response, forged):
        assert page.status_code == 200
        assert "確かめた後に内容が変わりました。もう一度確かめてください" in page.text
    assert "ER2026102499" in _dialog(response.text)


def test_typed_patient_id_of_another_patient_is_refused(config: AppConfig, store: OrderStore) -> None:
    """手で入れた患者ID が名簿・予約の患者のもので、氏名などが合わなければ、窓を出さずに断る."""
    sop_uid, _ = add_unscheduled_mpps(store)
    typed = {"patient": "manual", "alphabetic_family": "YAMADA", "alphabetic_given": "TARO", "sex": "M"}
    with _client(config, store) as (client, service):
        ordered = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
        roster = _post(client, f"/reconciliation/{sop_uid}", patient_id=ROSTER_ID, **typed)
        order = _post(client, f"/reconciliation/{sop_uid}", patient_id=ordered.patient.patient_id, **typed)
        assert service.count_orders() == 1
    assert roster.status_code == 400 and "<dialog" not in roster.text
    assert (
        "患者ID P000001 は、既にある患者（田中 博 1998-03-12 M）の患者ID です。"
        "入力した氏名・生年月日・性別と合いません。名簿から選ぶか、患者ID を確かめてください"
    ) in roster.text
    assert order.status_code == 400 and f"患者ID {ordered.patient.patient_id} は、既にある患者" in order.text


def test_typed_patient_is_refused_while_the_roster_cannot_be_read(
    config: AppConfig, store: OrderStore, tmp_path
) -> None:
    """名簿を読めないときは、名簿にだけある患者を見落とすので、手で入れた患者で照合しない."""
    sop_uid, _ = add_unscheduled_mpps(store)
    orders = config.orders.model_copy(update={"roster_path": str(tmp_path / "missing.yaml")})
    broken = config.model_copy(update={"orders": orders})
    with _client(broken, store) as (client, service):
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id=ROSTER_ID,
            alphabetic_family="YAMADA",
            alphabetic_given="TARO",
        )
        assert service.count_orders() == 0
    assert response.status_code == 400 and "<dialog" not in response.text
    assert "名簿を読めないので、患者ID が既にある患者のものかを確かめられません" in response.text


def test_typed_patient_id_of_the_same_patient_shows_the_known_patient(
    config: AppConfig, store: OrderStore
) -> None:
    """手で入れた患者ID の既にある患者と値が合えば、窓にその患者も並べる."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="manual",
            patient_id=ROSTER_ID,
            alphabetic_family="TANAKA",
            alphabetic_given="HIROSHI",
            birth_date="1998-03-12",
        )
    dialog = _dialog(response.text)
    assert "<th>既にある患者（同じ患者ID）</th>" in dialog
    assert _rows(dialog)[1] == ("氏名（漢字）", "不明 男性", "", "田中 博", "違う")
    assert _rows(dialog)[3] == ("氏名（英字）", "UNKNOWN MALE", "TANAKA HIROSHI", "TANAKA HIROSHI", "違う")


def test_roster_patient_gone_is_not_replaced_by_the_first(config: AppConfig, store: OrderStore) -> None:
    """送った名簿の患者が名簿に無ければ、先頭の患者を選んだ形で出さず、選び直させる."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        response = _post(client, f"/reconciliation/{sop_uid}", **_roster(roster_patient_id="P999999"))
    select = response.text.split('<select name="roster_patient_id"', 1)[1].split("</select>", 1)[0]
    assert response.status_code == 400 and "名簿に無い患者ID です" in response.text
    assert re.findall(r'<option value="([^"]*)" selected>', select) == [""]
    assert '<option value="" selected>選択してください</option>' in select


def test_patient_source_form_is_marked_for_the_script(config: AppConfig, store: OrderStore) -> None:
    """「名簿から選ぶ」「入力する」の選んでいない側を押せなくするのは app.js（form の印で見つける）."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        page = client.get(f"/reconciliation/{sop_uid}").text
        script = client.get("/static/app.js").text
    assert has_tag(
        page, "form", action=f"/reconciliation/{sop_uid}", **{"class": "w-form", "data-patient-source": None}
    )
    assert "form[data-patient-source]" in script and "syncPatientSource" in script
