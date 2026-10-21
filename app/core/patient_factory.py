"""架空の患者を乱数で作る（spec/01_orders.md 3 章）.

氏名は、よくある姓と名を組み合わせた架空のもの。実在の人を指さない。
Pure な処理（乱数は呼ぶ側が `random.Random` を渡す）。
"""

from __future__ import annotations

import random
from datetime import date

from .models import Patient, PersonName

# (英字, 漢字, カナ)。英字はヘボン式で長音を書かない（dicom-test-generator の名簿と同じ書き方）
FAMILY_NAMES: tuple[tuple[str, str, str], ...] = (
    ("SATO", "佐藤", "サトウ"),
    ("SUZUKI", "鈴木", "スズキ"),
    ("TAKAHASHI", "高橋", "タカハシ"),
    ("TANAKA", "田中", "タナカ"),
    ("ITO", "伊藤", "イトウ"),
    ("WATANABE", "渡辺", "ワタナベ"),
    ("YAMAMOTO", "山本", "ヤマモト"),
    ("NAKAMURA", "中村", "ナカムラ"),
    ("KOBAYASHI", "小林", "コバヤシ"),
    ("KATO", "加藤", "カトウ"),
    ("YOSHIDA", "吉田", "ヨシダ"),
    ("YAMADA", "山田", "ヤマダ"),
    ("SASAKI", "佐々木", "ササキ"),
    ("YAMAGUCHI", "山口", "ヤマグチ"),
    ("MATSUMOTO", "松本", "マツモト"),
    ("INOUE", "井上", "イノウエ"),
    ("KIMURA", "木村", "キムラ"),
    ("HAYASHI", "林", "ハヤシ"),
    ("SHIMIZU", "清水", "シミズ"),
    ("YAMAZAKI", "山崎", "ヤマザキ"),
    ("MORI", "森", "モリ"),
    ("IKEDA", "池田", "イケダ"),
    ("HASHIMOTO", "橋本", "ハシモト"),
    ("ISHIKAWA", "石川", "イシカワ"),
    ("OGAWA", "小川", "オガワ"),
    ("FUJITA", "藤田", "フジタ"),
    ("OKADA", "岡田", "オカダ"),
    ("GOTO", "後藤", "ゴトウ"),
    ("HASEGAWA", "長谷川", "ハセガワ"),
    ("MURAKAMI", "村上", "ムラカミ"),
)

MALE_GIVEN_NAMES: tuple[tuple[str, str, str], ...] = (
    ("HIROSHI", "博", "ヒロシ"),
    ("TAKESHI", "武", "タケシ"),
    ("KENJI", "健二", "ケンジ"),
    ("MAKOTO", "誠", "マコト"),
    ("SHOTA", "翔太", "ショウタ"),
    ("DAISUKE", "大輔", "ダイスケ"),
    ("TAKUYA", "拓也", "タクヤ"),
    ("KAZUO", "和夫", "カズオ"),
    ("MINORU", "稔", "ミノル"),
    ("HARUTO", "陽翔", "ハルト"),
    ("REN", "蓮", "レン"),
    ("YUTA", "雄太", "ユウタ"),
    ("SHIGERU", "茂", "シゲル"),
    ("ISAMU", "勇", "イサム"),
    ("RYOTA", "亮太", "リョウタ"),
)

FEMALE_GIVEN_NAMES: tuple[tuple[str, str, str], ...] = (
    ("YUKI", "由紀", "ユキ"),
    ("AKIKO", "明子", "アキコ"),
    ("MEGUMI", "恵", "メグミ"),
    ("YOKO", "洋子", "ヨウコ"),
    ("KEIKO", "恵子", "ケイコ"),
    ("SAKURA", "さくら", "サクラ"),
    ("MISAKI", "美咲", "ミサキ"),
    ("HARUKA", "遥", "ハルカ"),
    ("TOMOKO", "智子", "トモコ"),
    ("KAZUKO", "和子", "カズコ"),
    ("AYA", "彩", "アヤ"),
    ("NANAMI", "七海", "ナナミ"),
    ("MAI", "麻衣", "マイ"),
    ("SACHIKO", "幸子", "サチコ"),
    ("HINA", "陽菜", "ヒナ"),
)

MAX_AGE_YEARS = 95
PATIENT_ID_DIGITS = 7


def make_person_name(rng: random.Random, sex: str) -> PersonName:
    """姓と名を選んで、3つのコンポーネントグループの氏名にする."""
    family = rng.choice(FAMILY_NAMES)
    given_names = MALE_GIVEN_NAMES if sex == "M" else FEMALE_GIVEN_NAMES
    given = rng.choice(given_names)
    return PersonName(
        alphabetic=f"{family[0]}^{given[0]}",
        ideographic=f"{family[1]}^{given[1]}",
        phonetic=f"{family[2]}^{given[2]}",
    )


def make_patient_id(rng: random.Random, prefix: str) -> str:
    return f"{prefix}{rng.randrange(10**PATIENT_ID_DIGITS):0{PATIENT_ID_DIGITS}d}"


def make_patient(rng: random.Random, *, patient_id: str, reference_date: date) -> Patient:
    """乱数の患者を1人作る。年齢は `reference_date` の時点で 0〜95 歳."""
    sex = rng.choice(("M", "F"))
    age = rng.randint(0, MAX_AGE_YEARS)
    birth = _birth_date(rng, reference_date, age)
    height_cm, weight_kg = _body_size(rng, sex, age)
    return Patient(
        patient_id=patient_id,
        name=make_person_name(rng, sex),
        birth_date=birth.strftime("%Y%m%d"),
        sex=sex,
        weight_kg=weight_kg,
        size_m=round(height_cm / 100, 2),
    )


def _birth_date(rng: random.Random, reference: date, age: int) -> date:
    """`reference` の時点で満 `age` 歳になる生年月日（2/29 は 2/28 に寄せる）."""
    latest = _replace_year(reference, reference.year - age)
    earliest = _replace_year(reference, reference.year - age - 1)
    span = (latest - earliest).days
    offset = rng.randint(1, max(span, 1))
    return date.fromordinal(earliest.toordinal() + offset)


def _replace_year(value: date, year: int) -> date:
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


def _body_size(rng: random.Random, sex: str, age: int) -> tuple[float, float]:
    """年齢と性別から、だいたいの身長（cm）と体重（kg）を作る（試験用の目安）."""
    if age < 18:
        height = 50 + age * (6.5 if age < 12 else 5.5) + rng.uniform(-5, 5)
        height = min(height, 175 if sex == "M" else 162)
        bmi = rng.uniform(14, 21)
    else:
        mean = 171 if sex == "M" else 158
        height = rng.gauss(mean - max(age - 60, 0) * 0.15, 6)
        bmi = rng.uniform(17, 30)
    height = round(max(height, 45.0), 1)
    weight = round(bmi * (height / 100) ** 2, 1)
    return height, max(weight, 2.0)
