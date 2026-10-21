"""乱数の患者の試験."""

from __future__ import annotations

import random
from datetime import date

from app.core.patient_factory import make_patient, make_patient_id


def test_patient_values_are_in_range() -> None:
    rng = random.Random(0)
    reference = date(2026, 10, 21)
    for _ in range(300):
        patient = make_patient(rng, patient_id=make_patient_id(rng, "RE"), reference_date=reference)
        assert patient.patient_id.startswith("RE") and len(patient.patient_id) == 9
        assert patient.sex in ("M", "F")
        birth = date(int(patient.birth_date[:4]), int(patient.birth_date[4:6]), int(patient.birth_date[6:]))
        age = reference.year - birth.year - ((reference.month, reference.day) < (birth.month, birth.day))
        assert 0 <= age <= 95
        assert 0.45 <= patient.size_m <= 2.2
        assert 2.0 <= patient.weight_kg <= 200
        alphabetic, ideographic, phonetic = (
            patient.name.alphabetic,
            patient.name.ideographic,
            patient.name.phonetic,
        )
        assert alphabetic.count("^") == ideographic.count("^") == phonetic.count("^") == 1
        assert alphabetic.isascii() and alphabetic.upper() == alphabetic
        assert patient.name.to_dicom() == f"{alphabetic}={ideographic}={phonetic}"


def test_same_seed_same_patient() -> None:
    reference = date(2026, 10, 21)
    a = make_patient(random.Random(7), patient_id="X", reference_date=reference)
    b = make_patient(random.Random(7), patient_id="X", reference_date=reference)
    assert a == b
