"""CLI の試験."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.cli.main import main
from tests.conftest import ROOT


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    raw = yaml.safe_load((ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8"))
    raw["database"] = str(tmp_path / "ris.sqlite3")
    raw["orders"]["roster_path"] = str(ROOT / "data" / "patients_sample.yaml")
    path = tmp_path / "app_config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_create_list_status_show(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(
        capsys, "create", "CT=3", "MR", "--date", "20261021", "--seed", "1", "--json", "--config", str(config_file)
    )
    assert code == 0
    orders = json.loads(out)
    assert [o["modality"] for o in orders] == ["CT", "CT", "CT", "MR"]
    accession = orders[0]["accession_number"]

    code, out, _ = _run(capsys, "list", "--date", "20261021", "--config", str(config_file))
    assert code == 0 and out.count("\n") == 4 and accession in out

    code, out, _ = _run(capsys, "status", accession, "completed", "--config", str(config_file))
    assert code == 0 and "完了" in out

    code, out, _ = _run(capsys, "list", "--status", "scheduled", "--json", "--config", str(config_file))
    assert len(json.loads(out)) == 3

    code, out, _ = _run(capsys, "show", accession, "--config", str(config_file))
    assert code == 0 and "Scheduled Procedure Step Sequence" in out and accession in out


def test_errors_and_exit_codes(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, "create", "XA=1", "--config", str(config_file))
    assert code == 2 and "設定に無いモダリティ" in err
    code, _, err = _run(capsys, "create", "CT=1", "--interval", "-5", "--config", str(config_file))
    assert code == 2
    code, _, err = _run(capsys, "status", "NOPE", "completed", "--config", str(config_file))
    assert code == 3
    code, _, err = _run(capsys, "list", "--config", str(config_file.parent / "missing.yaml"))
    assert code == 2 and "not found" in err


def test_create_with_stations(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    raw["orders"]["modalities"]["CT"]["stations"].append(
        {"name": "CT2号機", "ae_title": "CT02", "station_name": "CT02"}
    )
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    code, out, _ = _run(
        capsys, "create", "CT=1", "MR=1", "--station", "CT2号機", "--station", "MR1号機",
        "--date", "20261021", "--json", "--config", str(config_file),
    )  # fmt: skip
    assert code == 0
    orders = json.loads(out)
    assert [(o["modality"], o["scheduled_station_ae_title"]) for o in orders] == [
        ("CT", "CT02"),
        ("MR", "MR01"),
    ]
    code, _, err = _run(capsys, "create", "CT=1", "--station", "CT9号機", "--config", str(config_file))
    assert code == 2 and "台帳に無い装置です: CT9号機" in err and "CT1号機、CT2号機" in err
    code, _, err = _run(
        capsys, "create", "CT=1", "--station", "CT1号機", "--station", "CT2号機", "--config", str(config_file)
    )
    assert code == 2 and "1つだけ" in err


def test_old_station_ae_option_is_gone(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["create", "CT=1", "--station-ae", "CT01", "--config", str(config_file)])
    assert exit_info.value.code == 2


def test_status_transitions(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "create", "CT=1", "--date", "20261021", "--json", "--config", str(config_file))
    accession = json.loads(out)[0]["accession_number"]
    code, out, _ = _run(capsys, "status", accession, "in_progress", "--config", str(config_file))
    assert code == 0 and "実施中" in out
    code, out, _ = _run(capsys, "status", accession, "completed", "--config", str(config_file))
    assert code == 0
    # 完了は終わりの状態。予定に戻せない
    code, _, err = _run(capsys, "status", accession, "scheduled", "--config", str(config_file))
    assert code == 2 and "完了の予約は予定に変更できません" in err
    # 同じ状態は何もしないで成功
    code, out, _ = _run(capsys, "status", accession, "completed", "--config", str(config_file))
    assert code == 0 and "完了" in out


def test_discontinued_status(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "create", "CT=1", "--date", "20261021", "--json", "--config", str(config_file))
    accession = json.loads(out)[0]["accession_number"]
    # 予定から中止へは変更できない（中止は始めた撮影を止めたこと）
    code, _, err = _run(capsys, "status", accession, "discontinued", "--config", str(config_file))
    assert code == 2 and "予定の予約は中止に変更できません" in err
    _run(capsys, "status", accession, "in_progress", "--config", str(config_file))
    code, out, _ = _run(capsys, "status", accession, "discontinued", "--config", str(config_file))
    assert code == 0 and "中止" in out


def _set_retake_mode(config_file: Path, mode: str) -> None:
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    raw["orders"]["retake_mode"] = mode
    config_file.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def test_retake(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "create", "CT=1", "--date", "20261021", "--json", "--config", str(config_file))
    accession = json.loads(out)[0]["accession_number"]
    # 予定の予約からは作れない
    _set_retake_mode(config_file, "new_order")
    code, _, err = _run(capsys, "retake", accession, "--config", str(config_file))
    assert code == 2 and "予定の予約からは撮り直しを作れません" in err
    _run(capsys, "status", accession, "in_progress", "--config", str(config_file))
    code, out, _ = _run(
        capsys, "retake", accession, "--date", "20261022", "--start", "10:30", "--json", "--config", str(config_file)
    )
    assert code == 0
    retake = json.loads(out)[0]
    assert retake["retake_of"] == accession and retake["accession_number"] != accession
    assert (retake["scheduled_date"], retake["scheduled_time"], retake["status"]) == ("20261022", "103000", "scheduled")
    code, out, _ = _run(capsys, "list", "--status", "discontinued", "--json", "--config", str(config_file))
    assert [o["accession_number"] for o in json.loads(out)] == [accession]


def test_retake_in_append_mode(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "create", "CT=1", "--date", "20261021", "--json", "--config", str(config_file))
    accession = json.loads(out)[0]["accession_number"]
    _run(capsys, "status", accession, "completed", "--config", str(config_file))
    code, _, err = _run(capsys, "retake", accession, "--config", str(config_file))
    assert code == 2 and "append" in err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "version")
    assert code == 0 and out.startswith("ris-emulator ")
