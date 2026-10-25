"""手で入れた患者の入力の確かめ：CLI（docs/spec/01_orders.md 3.4）."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.test_cli_reconcile import _config_file, _run, _store
from tests.conftest import add_unscheduled_mpps

BAD_INPUTS = [
    (["--patient-id", "X1", "--name", "佐藤^次郎"], "氏名（英字）は半角"),
    (["--patient-id", "X1", "--name", "SATO^JIRO=髙橋^太郎"], "氏名（漢字）に使えない字"),
    (["--patient-id", "X1", "--name", "SATO^JIRO=ﾔﾏﾀﾞ"], "氏名（漢字）に使えない字"),
    (["--patient-id", "患者01", "--name", "SATO^JIRO"], "患者ID は半角の英数字"),
    (["--patient-id", "X1", "--name", "A" * 65], "64 字以内"),
    (["--patient-id", "X1", "--name", "SATO^JIRO", "--birth-date", "20230229"], "暦にある日付"),
    (["--patient-id", "X1", "--name", "SATO^JIRO", "--birth-date", "20991231"], "今日以前"),
]


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


def test_refusal_does_not_echo_the_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config_file(tmp_path)
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name", "SATO=髙橋^太郎",
        "--visit-number", "V1", "--dry-run", "--config", str(config),
    )  # fmt: skip
    assert code == 2 and "髙" not in out + err
