"""生年月日の和暦と年齢の表示（画面だけで使う。DICOM・HL7 の値は西暦の YYYYMMDD のまま）.

規則は 1 つ：生年月日が元号の表のどの期間に入るかを日付で決め、年 ＝ 西暦の年 − 元号の始まりの年 ＋ 1。
明治より前（1868/10/22 以前）は元号を出さず、年齢だけを出す。元年は短い表示では数字の 1。
年齢は `on`（年齢を数える日）の満年齢。検査に結び付く画面は検査日、結び付かない画面は開いた日を渡す。
"""

from __future__ import annotations

from datetime import date, datetime

# （始まりの日, 漢字 1 字, 英字 1 字）。新しい元号から先に並べる
_ERAS = (
    (date(2019, 5, 1), "令", "R"),
    (date(1989, 1, 8), "平", "H"),
    (date(1926, 12, 25), "昭", "S"),
    (date(1912, 7, 30), "大", "T"),
    (date(1868, 10, 23), "明", "M"),
)


def parse_date(value: str) -> date | None:
    """DICOM の DA（YYYYMMDD）を日付にする。読めなければ None."""
    try:
        return datetime.strptime(value, "%Y%m%d").date() if len(value) == 8 and value.isdigit() else None
    except ValueError:
        return None


def age_on(born: date, on: date) -> int:
    """on の時点の満年齢（誕生日の当日に上がる。2/29 生まれは平年は 3/1）."""
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def era_label(born: date, letter: bool = False) -> str:
    """元号と年：昭50（letter なら S50）。明治より前は空の文字列."""
    for start, kanji, alpha in _ERAS:
        if born >= start:
            return f"{alpha if letter else kanji}{born.year - start.year + 1}"
    return ""


def _parts(value: str, on: date, letter: bool) -> tuple[str, str]:
    """（西暦の日付, 括弧の中身）。日付として読めなければ（そのままの値, 空）."""
    born = parse_date(value)
    if born is None:
        return (f"{value[:4]}/{value[4:6]}/{value[6:]}" if len(value) == 8 and value.isdigit() else value, "")
    items = [era_label(born, letter)]
    age = age_on(born, on)
    if age >= 0:
        items.append(f"{age}歳")
    inside = "・".join(item for item in items if item)
    return born.strftime("%Y/%m/%d"), inside


def birth_text(value: str, on: date) -> tuple[str, str]:
    """患者バナーの生年月日（漢字 1 字）：（1975/05/14, （昭50・51歳））。括弧は全角."""
    day, inside = _parts(value, on, letter=False)
    return day, f"（{inside}）" if inside else ""


def birth_cell(value: str, on: date) -> str:
    """一覧の表の生年月日の列（英字 1 字）：1975/05/14 (S50・51歳)。括弧は半角で前に半角の空白."""
    day, inside = _parts(value, on, letter=True)
    return f"{day} ({inside})" if inside else day
