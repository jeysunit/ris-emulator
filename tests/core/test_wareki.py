"""生年月日の和暦と年齢（変換 12 行と年齢の境目 7 行）と、入力の読み取り（受ける形 24 行と誤り 19 行）."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import ValidationError
from app.core.wareki import (
    BIRTH_FORMAT_MESSAGE,
    BIRTH_FUTURE_MESSAGE,
    age_on,
    birth_cell,
    birth_hint,
    birth_text,
    era_label,
    parse_birth_input,
    parse_date,
)

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


# 入力の読み取り（開いた日 2026/10/29。年齢は開いた日で数える）：（入力, 西暦, 読み取り結果）
SHOWA_50 = "1975/05/14（昭50・51歳）"
HEISEI_1 = "1989/01/08（平1・37歳）"
REIWA_1 = "2019/05/01（令1・7歳）"
LEAP = "2000/02/29（平12・26歳）"
INPUTS = [
    ("1975/05/14", "19750514", SHOWA_50),
    ("1975/5/14", "19750514", SHOWA_50),
    (" 1975/05/14 ", "19750514", SHOWA_50),
    ("S50/05/14", "19750514", SHOWA_50),
    ("s50/5/14", "19750514", SHOWA_50),
    ("Ｓ50/05/14", "19750514", SHOWA_50),
    ("昭50/05/14", "19750514", SHOWA_50),
    ("昭和50年5月14日", "19750514", SHOWA_50),
    ("H1/01/08", "19890108", HEISEI_1),
    ("H元/01/08", "19890108", HEISEI_1),
    ("平成元年1月8日", "19890108", HEISEI_1),
    ("R1/05/01", "20190501", REIWA_1),
    ("令元/05/01", "20190501", REIWA_1),
    ("S64/01/07", "19890107", "1989/01/07（昭64・37歳）"),
    ("H31/04/30", "20190430", "2019/04/30（平31・7歳）"),
    ("M1/10/23", "18681023", "1868/10/23（明1・158歳）"),
    ("M45/07/29", "19120729", "1912/07/29（明45・114歳）"),
    ("T1/07/30", "19120730", "1912/07/30（大1・114歳）"),
    ("T15/12/24", "19261224", "1926/12/24（大15・99歳）"),
    ("S1/12/25", "19261225", "1926/12/25（昭1・99歳）"),
    ("1868/10/22", "18681022", "1868/10/22（158歳）"),
    ("2000/02/29", "20000229", LEAP),
    ("H12/02/29", "20000229", LEAP),
    ("2026/10/29", "20261029", "2026/10/29（令8・0歳）"),
]

SHOWA_AFTER = "生年月日が昭和の範囲にありません。昭和は 1989/01/07 までです。平成1年は 1989/01/08 からです。"
TAISHO_AFTER = "生年月日が大正の範囲にありません。大正は 1926/12/24 までです。昭和1年は 1926/12/25 からです。"
MEIJI_AFTER = "生年月日が明治の範囲にありません。明治は 1912/07/29 までです。大正1年は 1912/07/30 からです。"
HEISEI_AFTER = "生年月日が平成の範囲にありません。平成は 2019/04/30 までです。令和1年は 2019/05/01 からです。"
HEISEI_BEFORE = "生年月日が平成の範囲にありません。平成は 1989/01/08 からです。昭和64年は 1989/01/07 までです。"
REIWA_BEFORE = "生年月日が令和の範囲にありません。令和は 2019/05/01 からです。平成31年は 2019/04/30 までです。"
TAISHO_BEFORE = "生年月日が大正の範囲にありません。大正は 1912/07/30 からです。明治45年は 1912/07/29 までです。"
SHOWA_BEFORE = "生年月日が昭和の範囲にありません。昭和は 1926/12/25 からです。大正15年は 1926/12/24 までです。"
MEIJI_BEFORE = "生年月日が明治の範囲にありません。明治は 1868/10/23 からです。"

# 読めない入力：（入力, 誤りの文）
BAD_INPUTS = [
    ("1975-05-14", BIRTH_FORMAT_MESSAGE),
    ("19750514", BIRTH_FORMAT_MESSAGE),
    ("s50.5.14", BIRTH_FORMAT_MESSAGE),
    ("S500514", BIRTH_FORMAT_MESSAGE),
    ("75/05/14", BIRTH_FORMAT_MESSAGE),
    ("1975/S50/05/14", BIRTH_FORMAT_MESSAGE),
    ("S0/01/01", BIRTH_FORMAT_MESSAGE),
    ("1975/13/01", BIRTH_FORMAT_MESSAGE),
    ("1975/02/30", BIRTH_FORMAT_MESSAGE),
    ("2001/02/29", BIRTH_FORMAT_MESSAGE),
    ("X50/01/01", BIRTH_FORMAT_MESSAGE),
    ("S64/01/08", SHOWA_AFTER),
    ("S65/01/01", SHOWA_AFTER),
    ("H31/05/01", HEISEI_AFTER),
    ("H1/01/07", HEISEI_BEFORE),
    ("R1/04/30", REIWA_BEFORE),
    ("M1/10/22", MEIJI_BEFORE),
    ("2026/10/30", BIRTH_FUTURE_MESSAGE),
    ("R8/10/30", BIRTH_FUTURE_MESSAGE),
]

# spec の決まりの例のうち、試験の組に無いもの（元号の範囲の外と、受けない全角の数字と区切り）
MORE_BAD_INPUTS = [
    ("大16/01/01", TAISHO_AFTER),
    ("明治46年1月1日", MEIJI_AFTER),
    ("T1/07/29", TAISHO_BEFORE),
    ("S1/12/24", SHOWA_BEFORE),
    ("S５０/05/14", BIRTH_FORMAT_MESSAGE),
    ("S50／05／14", BIRTH_FORMAT_MESSAGE),
    ("", BIRTH_FORMAT_MESSAGE),
]


@pytest.mark.parametrize(("text", "value", "hint"), INPUTS)
def test_birth_input_is_read(text: str, value: str, hint: str) -> None:
    assert parse_birth_input(text, TODAY).strftime("%Y%m%d") == value
    assert birth_hint(text, TODAY, TODAY) == (hint, "")


@pytest.mark.parametrize(("text", "message"), BAD_INPUTS + MORE_BAD_INPUTS)
def test_bad_birth_input_is_refused(text: str, message: str) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_birth_input(text, TODAY)
    assert caught.value.message == message
    if text:
        assert birth_hint(text, TODAY, TODAY) == ("", message)


def test_birth_input_messages() -> None:
    assert BIRTH_FORMAT_MESSAGE == "生年月日を読み取れません。1975/05/14 か S50/05/14 の形で入力してください。"
    assert BIRTH_FUTURE_MESSAGE == "生年月日が今日より後です。日付を確かめてください。"


def test_empty_birth_input_shows_nothing() -> None:
    assert birth_hint("", TODAY, TODAY) == ("", "")
    assert birth_hint("  ", TODAY, TODAY) == ("", "")


@pytest.mark.parametrize(
    ("on", "age"), [("20260410", 50), ("20260510", 51), ("20250509", 49), ("20261029", 51)]
)
def test_birth_hint_counts_the_age_on_the_given_day(on: str, age: int) -> None:
    """年齢を数える日の組：生年月日 1975/05/10。検査日（または開いた日）で数える."""
    assert birth_hint("1975/05/10", _date(on), TODAY) == (f"1975/05/10（昭50・{age}歳）", "")


def test_birth_after_the_counting_day_shows_no_age() -> None:
    """数える日より後で今日以前の生年月日は、年齢を出さない."""
    assert birth_hint("2026/10/01", _date("20260901"), TODAY) == ("2026/10/01（令8）", "")
