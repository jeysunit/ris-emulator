"""生年月日の和暦と年齢の表示、和暦の入力の読み取り（画面だけで使う。DICOM・HL7 の値は西暦の YYYYMMDD のまま）.

規則は 1 つ：生年月日が元号の表のどの期間に入るかを日付で決め、年 ＝ 西暦の年 − 元号の始まりの年 ＋ 1。
明治より前（1868/10/22 以前）は元号を出さず、年齢だけを出す。元年は短い表示では数字の 1。
年齢は `on`（年齢を数える日）の満年齢。検査に結び付く画面は検査日、結び付かない画面は開いた日を渡す。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from app.core.exceptions import ValidationError

# （始まりの日, 漢字 1 字, 英字 1 字, 正式名）。新しい元号から先に並べる
_ERAS = (
    (date(2019, 5, 1), "令", "R", "令和"),
    (date(1989, 1, 8), "平", "H", "平成"),
    (date(1926, 12, 25), "昭", "S", "昭和"),
    (date(1912, 7, 30), "大", "T", "大正"),
    (date(1868, 10, 23), "明", "M", "明治"),
)

# 生年月日の入力で読めないときと、今日より後のときの文（画面・CLI で同じ）
BIRTH_FORMAT_MESSAGE = "生年月日を読み取れません。1975/05/14 か S50/05/14 の形で入力してください。"
BIRTH_FUTURE_MESSAGE = "生年月日が今日より後です。日付を確かめてください。"

# 受ける形は 4 つ：西暦、英字 1 字、漢字 1 字、正式名。区切りと数字は半角だけ
_YEAR = r"([0-9]{1,2}|元)"
_DAY = r"([0-9]{1,2})"
_WESTERN = re.compile(rf"([0-9]{{4}})/{_DAY}/{_DAY}")
_SHORT = re.compile(rf"([MTSHR明大昭平令]){_YEAR}/{_DAY}/{_DAY}")
_FULL = re.compile(rf"(明治|大正|昭和|平成|令和){_YEAR}年{_DAY}月{_DAY}日")
# 元号の英字は小文字と全角も受ける（その 1 字だけを半角の大文字にする。全角の数字と ／ は受けない）
_ERA_LETTERS = str.maketrans("mtshrＭＴＳＨＲｍｔｓｈｒ", "MTSHRMTSHRMTSHR")


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
    for start, kanji, alpha, _name in _ERAS:
        if born >= start:
            return f"{alpha if letter else kanji}{born.year - start.year + 1}"
    return ""


def _real_date(year: int, month: int, day: int) -> date:
    """暦にある日付。無い日（2/30・平年の 2/29・13 月・0 年）は形の誤りとして断る."""
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValidationError(BIRTH_FORMAT_MESSAGE) from exc


def _era_date(index: int, year_text: str, month: int, day: int) -> date:
    """元号の年月日を西暦の日付にし、その元号の期間に入るかを確かめる."""
    start, _kanji, _alpha, name = _ERAS[index]
    year = 1 if year_text == "元" else int(year_text)
    if year == 0:
        raise ValidationError(BIRTH_FORMAT_MESSAGE)
    born = _real_date(start.year + year - 1, month, day)
    if born < start:
        message = f"生年月日が{name}の範囲にありません。{name}は {start:%Y/%m/%d} からです。"
        if index + 1 < len(_ERAS):
            previous_start, _, _, previous_name = _ERAS[index + 1]
            end = start - timedelta(days=1)
            last = end.year - previous_start.year + 1
            message += f"{previous_name}{last}年は {end:%Y/%m/%d} までです。"
        raise ValidationError(message)
    if index > 0:
        next_start, _, _, next_name = _ERAS[index - 1]
        if born >= next_start:
            end = next_start - timedelta(days=1)
            raise ValidationError(
                f"生年月日が{name}の範囲にありません。{name}は {end:%Y/%m/%d} までです。"
                f"{next_name}1年は {next_start:%Y/%m/%d} からです。"
            )
    return born


def parse_birth_input(value: str, today: date) -> date:
    """画面で入れた生年月日を読み取る。誤りは `ValidationError`（文は入れた値を含めない）.

    受ける形：`1975/05/14`・`S50/05/14`（英字は大文字・小文字・全角）・`昭50/05/14`・
    `昭和50年5月14日`。月と日の 0 は省いてよく、元号の年は `元` でもよい。前後の空白は捨てる。
    確かめる順：形が合わない（暦に無い日を含む）→ 元号の範囲の外 → 今日より後。
    空の値は形の誤りにする（空を許す欄は、呼ぶ側が先に空を扱う）.
    """
    text = value.strip()
    western = _WESTERN.fullmatch(text)
    if western:
        born = _real_date(*(int(part) for part in western.groups()))
    else:
        match = _SHORT.fullmatch(text[:1].translate(_ERA_LETTERS) + text[1:])
        match = match or _FULL.fullmatch(text)
        if match is None:
            raise ValidationError(BIRTH_FORMAT_MESSAGE)
        era, year_text, month, day = match.groups()
        index = next(i for i, era_row in enumerate(_ERAS) if era in era_row[1:])
        born = _era_date(index, year_text, int(month), int(day))
    if born > today:
        raise ValidationError(BIRTH_FUTURE_MESSAGE)
    return born


def birth_hint(value: str, on: date, today: date) -> tuple[str, str]:
    """入力欄の下の読み取り結果と誤りの文：（1975/05/14（昭50・51歳）, 空）か（空, 誤りの文）.

    年齢は `on`（年齢を数える日）の満年齢。今日より後かは `today` で見る。空の値はどちらも空.
    """
    if not value.strip():
        return "", ""
    try:
        born = parse_birth_input(value, today)
    except ValidationError as exc:
        return "", exc.message
    day, inside = birth_text(born.strftime("%Y%m%d"), on)
    return day + inside, ""


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
