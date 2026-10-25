"""手で入れた患者の入力の確かめ：照合の画面（docs/spec/01_orders.md 3.4）."""

from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.patient_input import (
    ALPHABETIC_MESSAGE,
    BIRTH_DATE_FUTURE_MESSAGE,
    IDEOGRAPHIC_MESSAGE,
    PATIENT_ID_MESSAGE,
)
from app.services.config import AppConfig
from app.services.store import OrderStore
from tests.conftest import add_unscheduled_mpps
from tests.web.test_reconciliation import _client, _post

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "static"


def test_roster_patient_is_not_held_to_the_manual_input_rules(
    config: AppConfig, store: OrderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """名簿から選んだ患者は、手入力の字種の規則（JIS X 0208）を受けない（UTF-8 の名簿の「髙橋」）."""
    from app.core.models import Patient, PersonName

    sop_uid, _ = add_unscheduled_mpps(store)
    roster = [
        Patient(
            patient_id="P900001",
            name=PersonName(alphabetic="TAKAHASHI^TARO", ideographic="髙橋^太郎"),
        )
    ]
    with _client(config, store) as (client, service):
        monkeypatch.setattr(service, "roster_patients", lambda: roster)
        response = _post(
            client,
            f"/reconciliation/{sop_uid}",
            patient="roster",
            roster_patient_id="P900001",
            procedure="CT0002",
        )
        assert response.status_code == 303
        assert service.count_orders() == 1


def _manual(**extra: str) -> dict[str, str]:
    return {"patient": "manual", "patient_id": "X1", "alphabetic_family": "SATO", **extra}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_manual(alphabetic_family="佐藤"), ALPHABETIC_MESSAGE),
        (_manual(alphabetic_given="ＪＩＲＯ"), ALPHABETIC_MESSAGE),
        (_manual(alphabetic_given="JIRO2"), ALPHABETIC_MESSAGE),
        (_manual(ideographic_family="髙橋"), IDEOGRAPHIC_MESSAGE),
        (_manual(ideographic_given="ﾀﾛｳ"), IDEOGRAPHIC_MESSAGE),
        (_manual(patient_id="患者01"), PATIENT_ID_MESSAGE),
        (_manual(patient_id="X|1"), PATIENT_ID_MESSAGE),
        (_manual(patient_id="A" * 65), "64 字以内"),
        (_manual(alphabetic_family="A" * 65), "64 字以内"),
        (_manual(alphabetic_family="SA^TO"), "氏名（英字）に ^ = \\ と制御文字は使えません"),
        (_manual(phonetic_family="あ=い"), "氏名（かな）に ^ = \\ と制御文字は使えません"),
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


def test_refusal_does_not_echo_the_value(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    with _client(config, store) as (client, _):
        text = _post(client, f"/reconciliation/{sop_uid}", **_manual(ideographic_family="髙橋")).text
        # 入れ直しのために欄には残るが、誤りの文には出さない
        alert = text.split('role="alert"', 1)[1].split("</p>", 1)[0]
        assert "髙" not in alert


def test_valid_manual_patient_is_accepted(config: AppConfig, store: OrderStore) -> None:
    sop_uid, _ = add_unscheduled_mpps(store)
    data = _manual(
        alphabetic_given="JIRO",
        ideographic_family="佐藤",
        ideographic_given="次郎",
        phonetic_family="さとう",
        phonetic_given="ジロウ",
        birth_date="1975-05-10",
        sex="M",
        procedure="",
    )
    with _client(config, store) as (client, service):
        response = _post(client, f"/reconciliation/{sop_uid}", **data)
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
        ("birth_date", "birth-date", BIRTH_DATE_FUTURE_MESSAGE),
    ):
        end = page.index(f'name="{name}"')
        label = page[page.rindex("<label", 0, end) : page.index("</label>", end)]
        assert f'data-check="{kind}"' in label, name
        assert f'data-message="{message}"' in label, name
        assert "aria-describedby=" in label and " hidden>" in label, name
        # 欄の下の誤りは読み上げない（画面の上の知らせだけが role="alert"）
        assert 'role="alert"' not in label, name
    # かなの欄は文字の種類を見ない（未決）
    end = page.index('name="phonetic_family"')
    assert "data-check" not in page[page.rindex("<label", 0, end) : page.index("</label>", end)]


def test_script_range_covers_every_jis_x_0208_character() -> None:
    """画面の漢字の確かめは、サーバーが許す字（JIS X 0208）を 1 字も止めない（含みすぎはよい）."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無いので、画面のスクリプトを動かせない")
    from app.core.patient_input import check_ideographic_group

    jis = [
        chr(code)
        for code in range(0x80, 0x10000)
        if not check_ideographic_group(chr(code)) and not 0xD800 <= code <= 0xDFFF
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


def test_server_accepts_iteration_marks() -> None:
    from app.core.patient_input import check_ideographic_group

    assert check_ideographic_group("すゞき^スヾキ") == ""


def test_script_checks_on_input_and_blocks_submit_while_invalid() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in ("data-check", "data-message", "setCustomValidity", "aria-invalid", "patient-id"):
        assert marker in script, marker
