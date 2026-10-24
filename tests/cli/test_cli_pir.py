"""CLI の `pir send` の試験（docs/spec/06_hl7_pir.md 5 章）."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.cli.main import main
from app.core.hl7 import unescape
from tests.conftest import ROOT
from tests.hl7.test_mllp import _ack, stub_receiver

NAME = "YAMADA^TARO=山田^太郎=ヤマダ^タロウ"


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    raw = yaml.safe_load((ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8"))
    raw["database"] = str(tmp_path / "ris.sqlite3")
    raw["orders"]["roster_path"] = str(ROOT / "data" / "patients_sample.yaml")
    raw["hl7"]["timeout_seconds"] = 2
    path = tmp_path / "app_config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_dry_run_a40_prints_without_sending(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a40", "--patient-id", "RE0000001", "--name", NAME,
        "--prior-patient-id", "ER0001", "--birth-date", "19800101", "--sex", "M",
        "--dry-run", "--config", str(config_file),
    )  # fmt: skip
    assert code == 0 and err == ""
    lines = out.splitlines()
    assert [line.split("|")[0] for line in lines] == ["MSH", "EVN", "PID", "MRG"]
    assert "ADT^A40^ADT_A39" in lines[0]
    assert lines[2].startswith("PID|1||RE0000001^^^RIS_EMU^PI||YAMADA^TARO^^^^^L^A~山田^太郎")
    assert lines[3].startswith("MRG|ER0001^^^RIS_EMU^PI")


def test_send_a40_to_a_receiver_that_accepts(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def respond(body: bytes) -> bytes:
        control_id = body.decode("utf-8").split("|")[9]
        return _ack("AA", control_id=unescape(control_id))

    with stub_receiver(respond) as receiver:
        code, out, err = _run(
            capsys,
            "pir", "send", "--kind", "a40", "--patient-id", "RE0000001", "--name", NAME,
            "--prior-patient-id", "ER0001", "--port", str(receiver.port), "--config", str(config_file),
        )  # fmt: skip
    assert code == 0 and "受理されました（AA）" in out and err == ""
    assert b"MRG|ER0001^^^RIS_EMU^PI" in receiver.received[0]


def test_send_orm_for_an_existing_order(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(
        capsys, "create", "CT=1", "--date", "20261021", "--seed", "1", "--json", "--config", str(config_file)
    )
    accession = json.loads(out)[0]["accession_number"]

    def respond(body: bytes) -> bytes:
        return _ack("AA", control_id=body.decode("utf-8").split("|")[9])

    with stub_receiver(respond) as receiver:
        code, out, _ = _run(
            capsys,
            "pir", "send", "--kind", "orm", "--accession", accession, "--patient-class", "E",
            "--port", str(receiver.port), "--config", str(config_file),
        )  # fmt: skip
    assert code == 0
    text = receiver.received[0].decode("utf-8")
    assert "ORC|NW|" in text and f"|{accession}|" in text and "PV1|1|E|" in text


def test_exit_5_when_receiver_rejects(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def respond(body: bytes) -> bytes:
        return _ack("AR", control_id=body.decode("utf-8").split("|")[9], text="unknown merge")

    with stub_receiver(respond) as receiver:
        code, _, err = _run(
            capsys,
            "pir", "send", "--kind", "a40", "--patient-id", "RE0000001", "--name", NAME,
            "--prior-patient-id", "ER0001", "--port", str(receiver.port), "--config", str(config_file),
        )  # fmt: skip
    assert code == 5 and "断られました" in err and "AR" in err and "unknown merge" in err


def test_receiver_text_with_escape_sequences_is_not_printed_raw(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def respond(body: bytes) -> bytes:
        control_id = body.decode("utf-8").split("|")[9]
        return _ack("AR", control_id=control_id, text="\x1b[2Jclear\x9b", err="X\x1b]0;t\x07")

    with stub_receiver(respond) as receiver:
        code, out, err = _run(
            capsys,
            "pir", "send", "--kind", "a40", "--patient-id", "RE0000001", "--name", NAME,
            "--prior-patient-id", "ER0001", "--port", str(receiver.port), "--config", str(config_file),
        )  # fmt: skip
    assert code == 5
    for stream in (out, err):
        assert "\x1b" not in stream and "\x9b" not in stream and "\x07" not in stream
    assert "\\u001b" in err


def test_input_values_with_control_characters_are_not_printed_raw(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """利用者が打った値（旧 ID・ホスト・氏名）も、端末に出す表示では制御・書式文字を見える形にする."""
    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a40", "--patient-id", "RE1", "--name", NAME,
        "--prior-patient-id", "ER\x1b[2J1", "--dry-run", "--config", str(config_file),
    )  # fmt: skip
    assert code == 2 and "\x1b" not in err and "\\u001b" in err

    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name", "YAMADA‮^TARO",
        "--visit-number", "V1", "--dry-run", "--config", str(config_file),
    )  # fmt: skip
    assert code == 0 and "‮" not in out and "\\u202e" in out
    assert len(out.splitlines()) == 4

    code, out, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name", NAME,
        "--visit-number", "V1", "--host", "h\x1b]0;x\x07", "--config", str(config_file),
    )  # fmt: skip
    assert code == 6 and "\x1b" not in err and "\x07" not in err


def test_exit_6_when_receiver_is_down(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    code, _, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE0000001", "--name", NAME,
        "--visit-number", "V1", "--port", str(port), "--config", str(config_file),
    )  # fmt: skip
    assert code == 6 and "送れませんでした" in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--kind", "a40", "--name", NAME, "--prior-patient-id", "ER1"], "--patient-id"),
        (["--kind", "a40", "--patient-id", "RE1", "--name", NAME], "--prior-patient-id"),
        (["--kind", "a40", "--patient-id", "RE1", "--name", NAME, "--prior-patient-id", "RE1"], "A08"),
        (["--kind", "a08", "--patient-id", "RE1", "--name", NAME], "PV1-19"),
        (["--kind", "a08", "--patient-id", "RE|1", "--name", NAME, "--visit-number", "V1"], "patient_id"),
        (["--kind", "a08", "--patient-id", "RE1", "--name", "A=B=C=D", "--visit-number", "V1"], "3 グループ"),
        (["--kind", "a08", "--patient-id", "RE1", "--name", "A\\B", "--visit-number", "V1"], "alphabetic"),
        (["--kind", "orm"], "--accession"),
        (["--kind", "a08", "--patient-id", "RE1", "--name", NAME, "--visit-number", "V1", "--port", "0"], "ポート"),
    ],
)
def test_input_errors_exit_2(
    config_file: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    code, _, err = _run(capsys, "pir", "send", *argv, "--dry-run", "--config", str(config_file))
    assert code == 2 and message in err


def test_unknown_accession_exits_3(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, "pir", "send", "--kind", "orm", "--accession", "NOPE", "--config", str(config_file))
    assert code == 3


def test_empty_issuer_namespace_is_refused(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    raw["orders"]["issuer_namespace"] = ""
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    code, _, err = _run(
        capsys,
        "pir", "send", "--kind", "a08", "--patient-id", "RE1", "--name", NAME, "--visit-number", "V1",
        "--dry-run", "--config", str(config_file),
    )  # fmt: skip
    assert code == 2 and "issuer_namespace" in err
