"""設定の `hl7` の節の試験（docs/spec/06_hl7_pir.md 5 章）."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.exceptions import ConfigurationError
from app.services.config import load_config
from tests.conftest import ROOT


def _write(tmp_path: Path, hl7: object) -> Path:
    raw = yaml.safe_load((ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8"))
    if hl7 is None:
        raw.pop("hl7")
    else:
        raw["hl7"] = hl7
    path = tmp_path / "app_config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def test_sample_config_has_hl7_section() -> None:
    config = load_config(ROOT / "config" / "app_config.yaml")
    assert (config.hl7.host, config.hl7.port) == ("127.0.0.1", 2575)
    header = config.hl7.header()
    assert (header.sending_application, header.receiving_facility, header.processing_id) == (
        "RIS_EMU",
        "PACS",
        "P",
    )


def test_hl7_section_is_optional(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, None))
    assert config.hl7.port == 2575 and config.hl7.timeout_seconds == 10


@pytest.mark.parametrize(
    ("hl7", "location"),
    [
        ({"port": 0}, "hl7.port"),
        ({"port": 70000}, "hl7.port"),
        ({"host": ""}, "hl7.host"),
        ({"processing_id": "X"}, "hl7.processing_id"),
        ({"timeout_seconds": 0}, "hl7.timeout_seconds"),
        ({"sending_application": ""}, "hl7.sending_application"),
        ({"receiving_facility": "A\rB"}, "hl7.receiving_facility"),
        ({"sending_facility": "x" * 181}, "hl7.sending_facility"),
    ],
)
def test_invalid_hl7_section_is_refused(tmp_path: Path, hl7: dict[str, object], location: str) -> None:
    with pytest.raises(ConfigurationError, match=location):
        load_config(_write(tmp_path, hl7))


def test_delimiters_are_allowed_in_names(tmp_path: Path) -> None:
    """区切り文字は送るときにエスケープするので、設定では断らない."""
    config = load_config(_write(tmp_path, {"sending_application": "A&B^C"}))
    assert config.hl7.header().sending_application == "A&B^C"
