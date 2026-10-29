"""生年月日の和暦と年齢（変換 12 行と年齢の境目 7 行）."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.wareki import age_on, birth_cell, birth_text, era_label, parse_date

TODAY = date(2026, 10, 29)

# （生年月日, 漢字 1 字の形, 英字 1 字の形）。空は元号なし
CONVERSIONS = [
    ("18681022", "", ""),
    ("18681023", "明1", "M1"),
    ("19120729", "明45", "M45"),
    ("19120730", "大1", "T1"),
    ("19261224", "大15", "T15"),
    ("19261225", "昭1", "S1"),
    ("19750514", "昭50", "S50"),
    ("19890107", "昭64", "S64"),
    ("19890108", "平1", "H1"),
    ("20190430", "平31", "H31"),
    ("20190501", "令1", "R1"),
    ("20261029", "令8", "R8"),
]

AGES = [
    ("19750514", "20260513", 50),
    ("19750514", "20260514", 51),
    ("20261029", "20261029", 0),
    ("20000229", "20260228", 25),
    ("20000229", "20260301", 26),
    ("20000229", "20280228", 27),
    ("20000229", "20280229", 28),
]


def _date(value: str) -> date:
    parsed = parse_date(value)
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(("value", "kanji", "letter"), CONVERSIONS)
def test_era_conversion(value: str, kanji: str, letter: str) -> None:
    born = _date(value)
    assert era_label(born) == kanji
    assert era_label(born, letter=True) == letter


@pytest.mark.parametrize(("value", "kanji", "letter"), CONVERSIONS)
def test_banner_and_list_forms(value: str, kanji: str, letter: str) -> None:
    day = f"{value[:4]}/{value[4:6]}/{value[6:]}"
    age = age_on(_date(value), TODAY)
    assert birth_text(value, TODAY) == (day, f"（{kanji + '・' if kanji else ''}{age}歳）")
    assert birth_cell(value, TODAY) == f"{day} ({letter + '・' if letter else ''}{age}歳)"


def test_before_meiji_shows_age_only() -> None:
    assert birth_text("18681022", TODAY) == ("1868/10/22", "（158歳）")
    assert birth_cell("18681022", TODAY) == "1868/10/22 (158歳)"


@pytest.mark.parametrize(("value", "today", "age"), AGES)
def test_age_boundaries(value: str, today: str, age: int) -> None:
    assert age_on(_date(value), _date(today)) == age


def test_birthday_today_is_age_zero_in_the_form() -> None:
    assert birth_text("20261029", TODAY) == ("2026/10/29", "（令8・0歳）")


def test_unreadable_value_is_kept_as_is() -> None:
    assert parse_date("19701399") is None
    assert birth_text("19701399", TODAY) == ("1970/13/99", "")
    assert birth_cell("", TODAY) == ""
