"""患者の名簿（YAML）の読み込み（spec/01_orders.md 3.2）.

形は dicom-test-generator の data/patients_master.yaml と同じ。
身長（size）は cm で書き、DICOM の Patient's Size（m）に直す。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.core.exceptions import ConfigurationError
from app.core.models import Patient, PersonName

CENTIMETERS_PER_METER = 100


class _RosterName(BaseModel):
    alphabetic: str = ""
    ideographic: str = ""
    phonetic: str = ""


class _RosterPatient(BaseModel):
    patient_id: str = Field(..., min_length=1, max_length=64)
    patient_name: _RosterName
    birth_date: str = ""
    sex: str = ""
    weight: float | None = None
    size: float | None = None  # cm


def load_roster(path: Path) -> list[Patient]:
    """名簿を読む。読めない・形が違えば ConfigurationError."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError("Roster file not found", {"path": str(path)}) from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError("Roster file could not be read", {"path": str(path)}) from exc
    entries = raw.get("patients") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigurationError("Roster must have a non-empty 'patients' list", {"path": str(path)})
    patients: list[Patient] = []
    for index, entry in enumerate(entries):
        try:
            item = _RosterPatient.model_validate(entry)
            patients.append(
                Patient(
                    patient_id=item.patient_id,
                    name=PersonName(**item.patient_name.model_dump()),
                    birth_date=item.birth_date,
                    sex=item.sex,
                    weight_kg=item.weight,
                    size_m=round(item.size / CENTIMETERS_PER_METER, 2) if item.size else None,
                )
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first["loc"])
            raise ConfigurationError(
                f"Invalid roster entry #{index + 1}: {location}: {first['msg']}",
                {"path": str(path)},
            ) from exc
    return patients
