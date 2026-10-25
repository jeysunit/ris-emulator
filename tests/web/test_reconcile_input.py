"""手で入れた患者の入力の確かめ：照合の画面（docs/spec/01_orders.md 3.4）."""

from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.models import CharacterSet, Patient, PersonName
from app.core.patient_input import (
    ALPHABETIC_MESSAGE,
    BIRTH_DATE_FUTURE_MESSAGE,
    IDEOGRAPHIC_MESSAGE,
    PATIENT_ID_MESSAGE,
    PHONETIC_MESSAGE,
    check_ideographic_group,
)
from app.services.config import AppConfig
from app.services.store import OrderStore
from tests.conftest import add_unscheduled_mpps
from tests.web.test_reconciliation import _client, _post, _reconcile

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "static"


def _with_orders(config: AppConfig, **update: object) -> AppConfig:
    return config.model_copy(update={"orders": config.orders.model_copy(update=update)})


def _manual(**extra: str) -> dict[str, str]:
    return {"patient": "manual", "patient_id": "X1", "alphabetic_family": "SATO", **extra}


def test_roster_patient_is_not_held_to_the_manual_input_rules(
    config: AppConfig, store: OrderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """名簿から選んだ患者は、手入力の規則を受けない（名簿の「髙橋」と半角カナのかな）."""
    sop_uid, _ = add_unscheduled_mpps(store)
    roster = [
        Patient(
            patient_id="P900001",
            name=PersonName(alphabetic="TAKAHASHI^TARO", ideographic="髙橋^太郎", phonetic="ﾀｶﾊｼ"),
        )
    ]
    with _client(config, store) as (client, service):
        monkeypatch.setattr(service, "roster_patients", lambda: roster)
        response = _reconcile(
            client,
            f"/reconciliation/{sop_uid}",
            patient="roster",
            roster_patient_id="P900001",
            procedure="CT0002",
        )
        assert response.status_code == 303
        assert service.count_orders() == 1


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_manual(alphabetic_family="佐藤"), ALPHABETIC_MESSAGE),
        (_manual(alphabetic_given="ＪＩＲＯ"), ALPHABETIC_MESSAGE),
        (_manual(alphabetic_given="JIRO2"), ALPHABETIC_MESSAGE),
        (_manual(phonetic_family="ｻﾄｳ"), PHONETIC_MESSAGE),
        (_manual(phonetic_given="ジロウ佐"), PHONETIC_MESSAGE),
        (_manual(phonetic_family="Sato"), PHONETIC_MESSAGE),
        (_manual(patient_id="患者01"), PATIENT_ID_MESSAGE),
        (_manual(patient_id="X|1"), PATIENT_ID_MESSAGE),
        (_manual(patient_id="A" * 65), "64 字以内"),
        (_manual(alphabetic_family="A" * 65), "64 字以内"),
        (_manual(alphabetic_family="SA^TO"), "氏名（英字）に ^ = \\ と制御文字は使えません"),
        (_manual(phonetic_family="ア=イ"), "氏名（かな）に ^ = \\ と制御文字は使えません"),
        (_manual(birth_date="2999-01-01"), BIRTH_DATE_FUTURE_MESSAGE),
        (_manual(birth_date="2023-02-29"), "暦にある日付"),
        (_manual(sex="X"), "性別"),
    ],
)
def test_bad_manual_patient_is_refused_in_japanese(
    config: AppConfig, store: OrderStore, data: dict[str, str], message: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        response = _post(client, f"/reconciliation/{sop_uid}", **data)
        text = html_lib.unescape(response.text)
        assert response.status_code == 400
        assert message in text and 'role="alert"' in text
        assert service.count_orders() == 0
        assert len(service.store.list_unlinked_mpps()) == 1


@pytest.mark.parametrize("field", ["ideographic_family", "ideographic_given"])
@pytest.mark.parametrize("name", ["髙橋", "山﨑", "ﾀﾛｳ"])
def test_jis_refuses_unrepresentable_ideographic_names(
    config: AppConfig, store: OrderStore, field: str, name: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    jis = _with_orders(config, default_character_set=CharacterSet.JIS)
    with _client(jis, store) as (client, service):
        response = _post(client, f"/reconciliation/{sop_uid}", **_manual(**{field: name}))
        text = html_lib.unescape(response.text)
        assert response.status_code == 400
        assert IDEOGRAPHIC_MESSAGE in text
        assert service.count_orders() == 0
        # 誤りの文には、入れた字を出さない
        alert = text.split('role="alert"', 1)[1].split("</p>", 1)[0]
        assert name not in alert


@pytest.mark.parametrize("name", ["髙橋", "山﨑"])
def test_utf8_accepts_names_outside_jis(config: AppConfig, store: OrderStore, name: str) -> None:
    """予約の文字コードが UTF-8（既定）なら、漢字の氏名を JIS X 0208 で断らない."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, service):
        response = _reconcile(
            client, f"/reconciliation/{sop_uid}", **_manual(ideographic_family=name, procedure="")
        )
        assert response.status_code == 303
        assert service.count_orders() == 1


def test_hiragana_in_the_phonetic_name_is_saved_as_katakana(
    config: AppConfig, store: OrderStore
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    data = _manual(
        phonetic_family="さとう", phonetic_given="じろう", birth_date="1975-05-10", procedure=""
    )
    with _client(config, store) as (client, service):
        response = _reconcile(client, f"/reconciliation/{sop_uid}", **data)
        assert response.status_code == 303
        order = service.list_orders()[0]
        assert order.patient.name.phonetic == "サトウ^ジロウ"


def test_test_mode_passes_kana_values_through(config: AppConfig, store: OrderStore) -> None:
    """試験の形：半角カナ・ひらがな・混ざった値をそのまま通す（長さと禁止の字は見る）."""
    sop_uid, _ = add_unscheduled_mpps(store)
    mode = _with_orders(config, patient_input_test_mode=True)
    with _client(mode, store) as (client, service):
        page = html_lib.unescape(client.get(f"/reconciliation/{sop_uid}").text)
        assert "かなの確かめ：試験の形" in page and "data-test-mode" in page
        bad = _post(client, f"/reconciliation/{sop_uid}", **_manual(phonetic_family="ﾔ" * 65))
        assert bad.status_code == 400
        response = _reconcile(
            client,
            f"/reconciliation/{sop_uid}",
            **_manual(phonetic_family="ﾔﾏﾀﾞ", phonetic_given="たろう", procedure=""),
        )
        assert response.status_code == 303
        assert service.list_orders()[0].patient.name.phonetic == "ﾔﾏﾀﾞ^たろう"


def test_test_mode_halfwidth_kana_with_jis_is_refused_by_the_encoding_check(
    config: AppConfig, store: OrderStore
) -> None:
    """試験の形でも、予約の文字コードが jis なら半角カナのかなは、保存の前の符号化の確かめで断る.

    かなの確かめは通る（試験の形）が、jis は半角カナを符号化できない。jis_kana なら通る。
    """
    sop_uid, _ = add_unscheduled_mpps(store)
    mode = _with_orders(
        config, patient_input_test_mode=True, default_character_set=CharacterSet.JIS
    )
    with _client(mode, store) as (client, service):
        response = _reconcile(
            client, f"/reconciliation/{sop_uid}", **_manual(phonetic_family="ﾔﾏﾀﾞ", procedure="")
        )
        assert response.status_code == 400
        assert "で書けません" in html_lib.unescape(response.text)
        assert service.count_orders() == 0
    kana = _with_orders(
        config, patient_input_test_mode=True, default_character_set=CharacterSet.JIS_KANA
    )
    with _client(kana, store) as (client, service):
        response = _reconcile(
            client, f"/reconciliation/{sop_uid}", **_manual(phonetic_family="ﾔﾏﾀﾞ", procedure="")
        )
        assert response.status_code == 303
        assert service.count_orders() == 1


def test_refusal_does_not_echo_the_value(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        text = _post(client, f"/reconciliation/{sop_uid}", **_manual(phonetic_family="ﾔﾏﾀﾞ")).text
        # 入れ直しのために欄には残るが、誤りの文には出さない
        alert = text.split('role="alert"', 1)[1].split("</p>", 1)[0]
        assert "ﾔ" not in alert


def test_valid_manual_patient_is_accepted(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    data = _manual(
        alphabetic_given="JIRO",
        ideographic_family="佐藤",
        ideographic_given="次郎",
        phonetic_family="サトウ",
        phonetic_given="ジロウ",
        birth_date="1975-05-10",
        sex="M",
        procedure="",
    )
    with _client(config, store) as (client, service):
        response = _reconcile(client, f"/reconciliation/{sop_uid}", **data)
        assert response.status_code == 303
        assert service.count_orders() == 1


def test_reconcile_form_marks_each_field_for_the_script(config: AppConfig, store: OrderStore) -> None:
    """入力した時に分かるよう、欄に確かめの種類・文・誤りの置き場を持たせる."""
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        page = html_lib.unescape(client.get(f"/reconciliation/{sop_uid}").text)
    for name, kind, message in (
        ("patient_id", "patient-id", PATIENT_ID_MESSAGE),
        ("alphabetic_family", "alphabetic", ALPHABETIC_MESSAGE),
        ("alphabetic_given", "alphabetic", ALPHABETIC_MESSAGE),
        ("ideographic_family", "ideographic", IDEOGRAPHIC_MESSAGE),
        ("ideographic_given", "ideographic", IDEOGRAPHIC_MESSAGE),
        ("phonetic_family", "phonetic", PHONETIC_MESSAGE),
        ("phonetic_given", "phonetic", PHONETIC_MESSAGE),
        ("birth_date", "birth-date", BIRTH_DATE_FUTURE_MESSAGE),
    ):
        end = page.index(f'name="{name}"')
        label = page[page.rindex("<label", 0, end) : page.index("</label>", end)]
        assert f'data-check="{kind}"' in label, name
        assert f'data-message="{message}"' in label, name
        assert "aria-describedby=" in label and " hidden>" in label, name
        # 欄の下の誤りは読み上げない（画面の上の知らせだけが role="alert"）
        assert 'role="alert"' not in label, name
    # 既定は UTF-8 なので漢字の欄は JIS の確かめを付けず、かなの欄は通常の形
    assert "data-charset-jis" not in page and "data-test-mode" not in page
    assert "かなの確かめ：全角カタカナ" in page


def test_form_marks_the_ideographic_fields_when_the_character_set_is_jis(
    config: AppConfig, store: OrderStore
) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(_with_orders(config, default_character_set=CharacterSet.JIS), store) as (client, _):
        page = client.get(f"/reconciliation/{sop_uid}").text
    for name in ("ideographic_family", "ideographic_given"):
        end = page.index(f'name="{name}"')
        assert "data-charset-jis" in page[page.rindex("<label", 0, end) : page.index("</label>", end)]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無いので、画面のスクリプトを動かせない")
    return node


def test_script_range_covers_every_jis_x_0208_character() -> None:
    """画面の漢字の確かめは、サーバーが許す字（JIS X 0208）を 1 字も止めない（含みすぎはよい）."""
    node = _node()
    jis = [
        chr(code)
        for code in range(0x80, 0x10000)
        if not check_ideographic_group(chr(code), CharacterSet.JIS) and not 0xD800 <= code <= 0xDFFF
    ]
    assert "ゞ" in jis and "ヾ" in jis and "髙" not in jis and len(jis) > 6000
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    match = re.search(r"var IDEOGRAPHIC_RANGES = .*?\n  }\n", source, re.S)
    assert match
    program = match.group(0) + "\nvar chars = JSON.parse(process.argv[1]);\n"
    program += "console.log(JSON.stringify(chars.filter(function (c) { return !isIdeographic(c); })));"
    result = subprocess.run(
        [node, "-e", program, json.dumps(jis)], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == []
    # 半角カナと JIS に無い字は止める
    probe = subprocess.run(
        [node, "-e", match.group(0) + "console.log(isIdeographic('ﾔ'), isIdeographic('😀'), isIdeographic('すゞき'));"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.split() == ["false", "false", "true"]


def test_script_phonetic_range_matches_the_server(tmp_path: Path) -> None:
    """画面のかなの確かめは、サーバーと同じ字を通し、同じ字を止める."""
    node = _node()
    from app.core.patient_input import check_phonetic_group

    chars = [chr(code) for code in range(0x20, 0x10000) if not 0xD800 <= code <= 0xDFFF]
    accepted = [c for c in chars if not check_phonetic_group(c) and c != "^"]
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    match = re.search(r"var PHONETIC_RANGES = .*?\n  }\n", source, re.S)
    assert match
    chars_file = tmp_path / "chars.json"
    chars_file.write_text(json.dumps(chars), encoding="utf-8")
    program = match.group(0) + "\nvar chars = JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8'));\n"
    program += "console.log(JSON.stringify(chars.filter(function (c) { return isPhonetic(c); })));"
    result = subprocess.run(
        [node, "-e", program, str(chars_file)], capture_output=True, text=True, check=True
    )
    assert "　" in accepted
    assert sorted(set(json.loads(result.stdout))) == sorted(accepted)


@pytest.mark.parametrize("character_set", [CharacterSet.JIS, CharacterSet.JIS_KANA])
@pytest.mark.parametrize("value", ["ﾀﾛｳ", "山田^ｱ"])
def test_server_refuses_halfwidth_kana_in_jis_like_the_screen(
    character_set: CharacterSet, value: str
) -> None:
    """jis_kana は半角カナを符号化できるが、画面は jis・jis_kana のどちらでも断る。サーバーも同じにする."""
    assert check_ideographic_group(value, character_set) == IDEOGRAPHIC_MESSAGE
    assert check_ideographic_group(value, CharacterSet.UTF8) == ""


def test_server_accepts_iteration_marks() -> None:
    assert check_ideographic_group("すゞき^スヾキ", CharacterSet.JIS) == ""


def test_script_checks_on_input_and_blocks_submit_while_invalid() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in ("data-check", "data-message", "setCustomValidity", "aria-invalid", "patient-id",
                   "convertPhonetic", "data-test-mode", "data-charset-jis"):
        assert marker in script, marker


def test_script_accepts_hiragana_while_typing_and_converts_before_submit() -> None:
    """Enter で送ると focusout が起きないので、送る前に直す。入力の途中のひらがなは誤りにしない."""
    node = _node()
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    ranges = re.search(r"var PHONETIC_RANGES = .*?\n  }\n", source, re.S)
    kana = re.search(r"var HIRAGANA = .*?function toKatakana.*?\n  }\n", source, re.S)
    assert ranges and kana
    program = ranges.group(0) + kana.group(0)
    program += "console.log(JSON.stringify([toKatakana('さとうジロー'), isPhonetic(toKatakana('さとう')), isPhonetic(toKatakana('ｻﾄｳ'))]));"
    result = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ["サトウジロー", True, False]
    # 送る前（submit）にも、ひらがなを直して確かめ直す（欄にいるまま Enter で送る場合）
    assert re.search(r'addEventListener\(\s*"submit",.*?convertPhonetic\(inputs\[i\]\);\s*checkField', source, re.S)
