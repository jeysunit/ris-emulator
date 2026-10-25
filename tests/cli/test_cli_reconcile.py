"""CLI の `reconcile` の試験（docs/spec/07_reconciliation.md 6 章）."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.cli.main import main
from app.services.store import OrderStore
from tests.conftest import ROOT, add_unscheduled_mpps
from tests.hl7.stub import ack, stub_receiver


def _config_file(tmp_path: Path, port: int = 1) -> Path:
    raw = yaml.safe_load((ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8"))
    raw["database"] = str(tmp_path / "ris.sqlite3")
    raw["orders"]["roster_path"] = str(ROOT / "data" / "patients_sample.yaml")
    raw["hl7"]["port"] = port
    raw["hl7"]["timeout_seconds"] = 2
    path = tmp_path / "app_config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _store(tmp_path: Path) -> OrderStore:
    return OrderStore(tmp_path / "ris.sqlite3")


def test_list_is_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config_file(tmp_path)
    code, out, _ = _run(capsys, "reconcile", "list", "--config", str(config))
    assert code == 0 and "未照合の撮影はありません" in out


def test_list_text_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(_store(tmp_path))
    config = _config_file(tmp_path)
    code, out, _ = _run(capsys, "reconcile", "list", "--config", str(config))
    assert code == 0 and sop_uid in out and study_uid in out and "ER2026102400" in out
    code, out, _ = _run(capsys, "reconcile", "list", "--json", "--config", str(config))
    row = json.loads(out)[0]
    assert (row["sop_instance_uid"], row["patient_id"], row["modality"]) == (sop_uid, "ER2026102400", "CT")
    assert row["patient_name"] == "UNKNOWN^MALE=不明^男性=フメイ^ダンセイ" and row["problem"] == ""


def test_run_with_roster_patient(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sop_uid, study_uid = add_unscheduled_mpps(_store(tmp_path))
    with stub_receiver(lambda text: ack("AA", text)) as receiver:
        config = _config_file(tmp_path, receiver.port)
        code, out, err = _run(
            capsys, "reconcile", "run", sop_uid, "--roster-patient-id", "P000001", "--config", str(config)
        )
    assert code == 0 and err == ""
    assert receiver.types == ["ADT^A40", "ORM^O01"]
    assert out.count("送信完了") == 2 and "ADT^A40" in out
    assert f"ZDS|{study_uid}^" in receiver.received[1]
    code, out, _ = _run(capsys, "reconcile", "list", "--config", str(config))
    assert "未照合の撮影はありません" in out


def test_run_with_typed_patient_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sop_uid, _ = add_unscheduled_mpps(_store(tmp_path))
    with stub_receiver(lambda text: ack("AA", text)) as receiver:
        config = _config_file(tmp_path, receiver.port)
        code, out, _ = _run(
            capsys, "reconcile", "run", sop_uid,
            "--patient-id", "X0001", "--name", "SATO^JIRO=佐藤^次郎", "--birth-date", "19750405", "--sex", "M",
            "--procedure", "CT0003", "--department", "外科", "--json", "--config", str(config),
        )  # fmt: skip
    result = json.loads(out)
    assert code == 0 and result["sop_instance_uid"] == sop_uid
    assert [d["outcome"] for d in result["deliveries"]] == ["accepted", "accepted"]
    code, out, _ = _run(capsys, "show", result["accession_number"], "--config", str(config))
    assert "CT0003" in out


def test_rejected_gives_exit_5_and_resend_fixes_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sop_uid, _ = add_unscheduled_mpps(_store(tmp_path))
    answers = iter(["AR", "AA", "AA"])
    with stub_receiver(lambda text: ack(next(answers), text, "no such patient")) as receiver:
        config = _config_file(tmp_path, receiver.port)
        code, out, _ = _run(
            capsys, "reconcile", "run", sop_uid, "--roster-patient-id", "P000001", "--config", str(config)
        )
        assert code == 5
        assert "拒否：AR no such patient" in out and "送信待ち" in out
        accession = out.split(":")[0]
        code, out, _ = _run(capsys, "reconcile", "resend", accession, "--config", str(config))
    assert code == 0 and out.count("送信完了") == 2
    assert receiver.received[0] == receiver.received[1]


def test_unreachable_gives_exit_6(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sop_uid, _ = add_unscheduled_mpps(_store(tmp_path))
    config = _config_file(tmp_path, 1)
    code, out, _ = _run(
        capsys, "reconcile", "run", sop_uid, "--roster-patient-id", "P000001", "--config", str(config)
    )
    assert code == 6 and "送信失敗" in out


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ([], "--roster-patient-id か"),
        (["--patient-id", "X1"], "--roster-patient-id か"),
        (["--roster-patient-id", "NOPE"], "名簿に無い患者ID"),
        (["--roster-patient-id", "P000001", "--patient-id", "X1"], "同時に指定できません"),
        (["--patient-id", "X1", "--name", "A", "--birth-date", "19751345"], "暦にある日付"),
        (["--roster-patient-id", "P000001", "--procedure", "CT9999"], "CT9999"),
    ],
)
def test_input_errors_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    sop_uid, _ = add_unscheduled_mpps(_store(tmp_path))
    config = _config_file(tmp_path)
    code, _, err = _run(capsys, "reconcile", "run", sop_uid, *extra, "--config", str(config))
    assert code == 2 and message in err
    assert _store(tmp_path).list_unlinked_mpps()[0].sop_instance_uid == sop_uid


def test_unknown_targets_exit_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config_file(tmp_path)
    code, _, err = _run(
        capsys, "reconcile", "run", "9.9.9", "--roster-patient-id", "P000001", "--config", str(config)
    )
    assert code == 3 and "MPPS not found" in err
    code, _, err = _run(capsys, "reconcile", "resend", "RE000", "--config", str(config))
    assert code == 3 and "Reconciliation not found" in err


def test_second_run_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sop_uid, _ = add_unscheduled_mpps(_store(tmp_path))
    with stub_receiver(lambda text: ack("AA", text)) as receiver:
        config = _config_file(tmp_path, receiver.port)
        args = ("reconcile", "run", sop_uid, "--roster-patient-id", "P000001", "--config", str(config))
        assert _run(capsys, *args)[0] == 0
        code, _, err = _run(capsys, *args)
    assert code == 2 and "すでに予約に結び付いています" in err


@pytest.mark.parametrize("outcome,expected", [("AA", 0), ("AE", 5), ("XX", 6)])
def test_status_exit_code_and_manual_ca_dry_run(tmp_path, capsys, outcome, expected):
    store = _store(tmp_path)
    uid, _ = add_unscheduled_mpps(store)
    answers = iter(["AA", "AA", outcome])
    with stub_receiver(lambda text: ack(next(answers), text)) as receiver:
        config = _config_file(tmp_path, receiver.port)
        code, _, _ = _run(capsys, "reconcile", "run", uid, "--roster-patient-id", "P000001", "--config", str(config))
        assert code == 0
        accession = store.get_mpps(uid).accession_numbers[0]
        code, out, _ = _run(capsys, "status", accession, "cancelled", "--config", str(config))
        assert code == expected and "ORM^O01（CA）" in out
    code, out, _ = _run(capsys, "pir", "send", "--kind", "orm", "--accession", accession,
                         "--order-control", "CA", "--dry-run", "--config", str(config))
    assert code == 0 and "ORC|CA|" in out
