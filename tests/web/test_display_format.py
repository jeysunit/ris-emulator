"""画面の日付・日時・性別の書き方（yyyy/MM/dd・yyyy/MM/dd HH:mm・男・女・その他・不明）."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.core.wareki import birth_cell
from app.web.app import SEX_LABELS, birth_parts, when, ymd


def test_dates_use_slashes() -> None:
    assert ymd("19980312") == "1998/03/12"
    assert ymd("") == "" and ymd("1998") == "1998" and ymd("1998031x") == "1998031x"


def test_record_times_drop_seconds_and_offset() -> None:
    assert when("2026-10-25T23:19:06+09:00") == "2026/10/25 23:19"
    assert when("2026-10-25T08:30:00") == "2026/10/25 08:30"
    assert when("") == "" and when("not a time") == "not a time"


def _patient(birth_date: str, sex: str) -> SimpleNamespace:
    return SimpleNamespace(birth_date=birth_date, sex=sex)


def test_banner_birth_date_has_era_age_and_sex() -> None:
    today = date(2026, 10, 25)
    assert birth_parts(_patient("19700401", "M"), today) == ("1970/04/01", "（昭45・56歳）男")
    assert birth_parts(_patient("19701026", "F"), today) == ("1970/10/26", "（昭45・55歳）女")
    assert birth_parts(_patient("19701025", "O"), today) == ("1970/10/25", "（昭45・56歳）その他")
    # 日付として読めなければ元号も年齢も付けない。性別は残す
    assert birth_parts(_patient("19701399", "M"), today) == ("1970/13/99", " 男")
    assert birth_parts(_patient("", "M"), today) == ("", "男")
    assert birth_parts(_patient("", ""), today) == ("", "")
    # 今日より後の生年月日は年齢を出さない
    assert birth_parts(_patient("20261026", "F"), today) == ("2026/10/26", "（令8）女")
    # 明治より前は元号を出さず、年齢だけ
    assert birth_parts(_patient("18600303", "M"), today) == ("1860/03/03", "（166歳）男")


def test_list_birth_date_uses_one_letter_era_and_half_width_parentheses() -> None:
    today = date(2026, 10, 25)
    assert birth_cell("19870314", today) == "1987/03/14 (S62・39歳)"
    assert birth_cell("18600303", today) == "1860/03/03 (166歳)"
    assert birth_cell("", today) == "" and birth_cell("19701399", today) == "1970/13/99"


def test_sex_labels_hide_the_coded_values() -> None:
    assert SEX_LABELS == {"M": "男", "F": "女", "O": "その他", "U": "不明"}
