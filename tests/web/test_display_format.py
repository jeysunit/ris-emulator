"""画面の日付・日時・性別の書き方（yyyy/MM/dd・yyyy/MM/dd HH:mm・男・女・その他・不明）."""

from __future__ import annotations

from datetime import date

from app.web.app import SEX_LABELS, birth, when, ymd


def test_dates_use_slashes() -> None:
    assert ymd("19980312") == "1998/03/12"
    assert ymd("") == "" and ymd("1998") == "1998" and ymd("1998031x") == "1998031x"


def test_record_times_drop_seconds_and_offset() -> None:
    assert when("2026-10-25T23:19:06+09:00") == "2026/10/25 23:19"
    assert when("2026-10-25T08:30:00") == "2026/10/25 08:30"
    assert when("") == "" and when("not a time") == "not a time"


def test_birth_date_with_age() -> None:
    today = date(2026, 10, 25)
    assert birth("19700401", today) == "1970/04/01（56 歳）"
    assert birth("19701026", today) == "1970/10/26（55 歳）"
    assert birth("19701025", today) == "1970/10/25（56 歳）"
    # 日付として読めなければ年齢を付けない
    assert birth("", today) == "" and birth("19701399", today) == "1970/13/99"


def test_sex_labels_hide_the_coded_values() -> None:
    assert SEX_LABELS == {"M": "男", "F": "女", "O": "その他", "U": "不明"}
