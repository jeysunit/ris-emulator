"""手で入れた患者の入力の確かめ：CLI（docs/spec/01_orders.md 3.4）."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.cli.test_cli_reconcile import _config_file, _run, _store
from tests.conftest import add_unscheduled_mpps

BAD_INPUTS = [
    (["--patient-id", "X1", "--name", "佐藤^次郎"], "氏名（英字）は半角"),
    (["--patient-id", "X1", "--name", "SATO^JIRO==ｻﾄｳ"], "氏名（かな）は全角のカタカナ"),
    (["--patient-id", "X1", "--name", "SATO^JIRO==Sato"], "氏名（かな）は全角のカタカナ"),
    (["--patient-id", "患者01", "--name", "SATO^JIRO"], "患者ID は半角の英数字"),
    (["--patient-id", "X1", "--name", "A" * 65], "64 字以内"),
    (["--patient-id", "X1", "--name", "SATO^JIRO", "--birth-date", "20230229"], "生年月日を読み取れません"),
    (["--patient-id", "X1", "--name", "SATO^JIRO", "--birth-date", "20991231"], "生年月日が今日より後です"),
]
# 予約の文字コードが JIS のときだけ断る漢字の氏名
JIS_BAD_INPUTS = [
    (["--patient-id", "X1", "--name", "SATO^JIRO=髙橋^太郎"], "この文字コードでは表せない字"),
    (["--patient-id", "X1", "--name", "SATO^JIRO=山﨑"], "この文字コードでは表せない字"),
    (["--patient-id", "X1", "--name", "SATO^JIRO=ﾔﾏﾀﾞ"], "この文字コードでは表せない字"),
]


def _config_with_orders(tmp_path: Path, **orders: object) -> Path:
    path = _config_file(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["orders"].update(orders)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize(("extra", "message"), BAD_INPUTS)
def test_reconcile_run_refuses_bad_patient(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(_store(tmp_path))
    config = _config_file(tmp_path)
    code, _, err = _run(capsys, "reconcile", "run", sop_uid, *extra, "--config", str(config))
    assert code == 2 and message in err
    # 照合は何も残さない
    assert _store(tmp_path).list_unlinked_mpps()[0].sop_instance_uid == sop_uid


@pytest.mark.parametrize(("extra", "message"), BAD_INPUTS)
def test_pir_send_refuses_bad_patient(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    config = _config_file(tmp_path)
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", *extra, "--visit-number", "V1", "--dry-run",
        "--config", str(config),
    )  # fmt: skip
    assert code == 2 and message in err
    assert out == ""


@pytest.mark.parametrize(("extra", "message"), JIS_BAD_INPUTS)
def test_jis_refuses_unrepresentable_ideographic_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    config = _config_with_orders(tmp_path, default_character_set="jis")
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", *extra, "--visit-number", "V1", "--dry-run",
        "--config", str(config),
    )  # fmt: skip
    assert code == 2 and message in err and out == ""
    assert not any(char in err for char in "髙﨑ﾔ")


def test_utf8_accepts_names_outside_jis_and_hiragana_becomes_katakana(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config_file(tmp_path)
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name",
        "TAKAHASHI^TARO=髙橋^太郎=たかはし^たろう", "--visit-number", "V1", "--dry-run",
        "--config", str(config),
    )  # fmt: skip
    assert code == 0, err
    assert "髙橋^太郎" in out and "タカハシ^タロウ" in out and "たかはし" not in out


def test_test_mode_passes_kana_values_through(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config_with_orders(tmp_path, patient_input_test_mode=True)
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name",
        "SATO^JIRO==ｻﾄｳ^じろう", "--visit-number", "V1", "--dry-run", "--config", str(config),
    )  # fmt: skip
    assert code == 0, err
    assert "ｻﾄｳ^じろう" in out


def test_refusal_does_not_echo_the_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config_file(tmp_path)
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name", "SATO==ｻﾄｳ",
        "--visit-number", "V1", "--dry-run", "--config", str(config),
    )  # fmt: skip
    assert code == 2 and "ｻ" not in out + err
