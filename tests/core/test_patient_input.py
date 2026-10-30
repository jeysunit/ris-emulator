"""手で入れた患者の入力の確かめ（docs/spec/01_orders.md 3.4）."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import ValidationError
from app.core.models import CharacterSet, Patient, PersonName
from app.core.patient_input import (
    ALPHABETIC_MESSAGE,
    BIRTH_DATE_FORMAT_MESSAGE,
    BIRTH_DATE_FUTURE_MESSAGE,
    IDEOGRAPHIC_MESSAGE,
    INPUT_MESSAGES,
    PATIENT_ID_MESSAGE,
    PHONETIC_MESSAGE,
    birth_date_from_cli,
    check_name_component,
    check_name_group,
    check_phonetic_group,
    to_katakana,
    validate_birth_date,
    validate_patient_id_input,
    validate_patient_input,
    validate_person_name,
    validate_sex,
)

TODAY = date(2026, 10, 25)


@pytest.mark.parametrize("value", ["SATO^JIRO", "O'BRIEN^MARY-ANN", "SMITH", "Sato Jiro"])
def test_alphabetic_group_accepts_letters_space_hyphen_apostrophe(value: str) -> None:
    assert check_name_group("alphabetic", "英字", value) == ""


@pytest.mark.parametrize(
    "value", ["佐藤^次郎", "ＳＡＴＯ^ＪＩＲＯ", "ﾔﾏﾀﾞ", "JIRO2", "A.B", "A_B", "A,B", "Ünal", "A/B"]
)
def test_alphabetic_group_refuses_other_characters(value: str) -> None:
    assert check_name_group("alphabetic", "英字", value) == ALPHABETIC_MESSAGE


@pytest.mark.parametrize("value", ["佐藤^次郎", "高橋^あ", "ヤマダ", "佐藤　次郎", "佐藤^JIRO", "すゞき"])
@pytest.mark.parametrize("character_set", list(CharacterSet))
def test_ideographic_group_accepts_jis_x_0208_in_every_character_set(
    value: str, character_set: CharacterSet
) -> None:
    assert check_name_group("ideographic", "漢字", value, character_set) == ""


@pytest.mark.parametrize("value", ["髙橋^太郎", "山﨑^太郎", "𠮷田", "佐藤😀"])
def test_ideographic_group_utf8_accepts_characters_outside_jis(value: str) -> None:
    """予約の文字コードが UTF-8 なら、JIS X 0208 に無い字も受ける（既定）."""
    assert check_name_group("ideographic", "漢字", value) == ""
    assert check_name_group("ideographic", "漢字", value, CharacterSet.UTF8) == ""


@pytest.mark.parametrize("value", ["髙橋^太郎", "山﨑^太郎", "ﾔﾏﾀﾞ", "佐藤😀", "𠮷田"])
@pytest.mark.parametrize("character_set", [CharacterSet.JIS, CharacterSet.JIS_KANA])
def test_ideographic_group_jis_refuses_unrepresentable_characters(
    value: str, character_set: CharacterSet
) -> None:
    if value == "ﾔﾏﾀﾞ" and character_set is CharacterSet.JIS_KANA:
        return  # jis_kana は半角カナを表せる
    message = check_name_group("ideographic", "漢字", value, character_set)
    assert message == IDEOGRAPHIC_MESSAGE
    assert "この文字コードでは表せない字" in message
    assert not any(char in message for char in "髙橋太郎😀𠮷田山﨑")


@pytest.mark.parametrize("value", ["サトウ^ジロウ", "サトウ", "ア ー", "ガッコウ・ヴ", "ヽヾ"])
def test_phonetic_group_accepts_full_width_katakana(value: str) -> None:
    assert check_phonetic_group(value) == ""
    assert check_name_group("phonetic", "かな", value) == ""


@pytest.mark.parametrize("value", ["ｻﾄｳ", "ｻﾄｳ^ｼﾞﾛｳ", "さとう", "サトウ佐", "Sato", "サトウ1", "ｱ"])
def test_phonetic_group_refuses_everything_else(value: str) -> None:
    assert check_phonetic_group(value) == PHONETIC_MESSAGE
    assert PHONETIC_MESSAGE == "氏名（かな）は全角のカタカナで入力してください。"


def test_phonetic_group_test_mode_passes_anything_through() -> None:
    """試験の形：半角カナ・ひらがな・混ざった値をそのまま通す（長さと禁止の字は見る）."""
    for value in ("ｻﾄｳ^ｼﾞﾛｳ", "さとう^じろう", "サトウ^じろう", "ｱあア", "Sato"):
        assert check_phonetic_group(value, test_mode=True) == ""
        assert check_name_group("phonetic", "かな", value, test_mode=True) == ""
    assert check_name_group("phonetic", "かな", "あ" * 65, test_mode=True)
    assert check_name_group("phonetic", "かな", "あ\\い", test_mode=True)
    assert check_name_group("phonetic", "かな", "ｱ") == PHONETIC_MESSAGE


def test_phonetic_group_accepts_both_widths_of_space() -> None:
    """長音と空白は可。空白は半角も全角（U+3000）も受ける."""
    assert check_phonetic_group("サトー　ジロウ サトウ") == ""


def test_hiragana_becomes_katakana_and_other_characters_stay() -> None:
    assert to_katakana("さとう じろう") == "サトウ ジロウ"
    assert to_katakana("ゔゝゞ") == "ヴヽヾ"
    assert to_katakana("ﾔﾏﾀﾞ山A") == "ﾔﾏﾀﾞ山A"


def test_phonetic_group_still_gets_common_checks() -> None:
    assert "64 字以内" in check_name_group("phonetic", "かな", "ア" * 65)
    assert check_name_group("phonetic", "かな", "ア\\イ")
    assert check_name_group("phonetic", "かな", "ア\x1bイ")
    assert check_name_group("phonetic", "かな", "ア=イ")


def test_group_limits() -> None:
    assert check_name_group("alphabetic", "英字", "A" * 64) == ""
    assert "64 字以内" in check_name_group("alphabetic", "英字", "A" * 65)
    assert check_name_group("alphabetic", "英字", "A^B^C^D^E") == ""
    assert "5 つ" in check_name_group("alphabetic", "英字", "A^B^C^D^E^F")


def test_name_component_refuses_separators_and_controls() -> None:
    assert check_name_component("英字", "SATO") == ""
    for value in ("SA^TO", "SA=TO", "SA\\TO", "SA\x1bTO"):
        assert "氏名（英字）" in check_name_component("英字", value)


def test_validate_person_name_names_the_failing_group() -> None:
    validate_person_name(PersonName(alphabetic="SATO^JIRO", ideographic="佐藤^次郎", phonetic="サトウ"))
    validate_person_name(PersonName(ideographic="佐藤^次郎"))
    with pytest.raises(ValidationError, match="氏名（英字）は半角"):
        validate_person_name(PersonName(alphabetic="佐藤"))
    with pytest.raises(ValidationError, match="氏名（漢字）に、この文字コードでは表せない字"):
        validate_person_name(
            PersonName(alphabetic="TAKAHASHI", ideographic="髙橋"), CharacterSet.JIS
        )
    validate_person_name(PersonName(alphabetic="TAKAHASHI", ideographic="髙橋"))
    with pytest.raises(ValidationError, match="氏名（かな）は全角のカタカナ"):
        validate_person_name(PersonName(alphabetic="SATO", phonetic="さとう"))
    validate_person_name(PersonName(alphabetic="SATO", phonetic="ｻﾄｳ"), test_mode=True)


@pytest.mark.parametrize("value", ["P000001", "ID-1.2_3/4", "A" * 64])
def test_patient_id_accepts(value: str) -> None:
    validate_patient_id_input(value)


@pytest.mark.parametrize(
    "value",
    ["", "  ", " X1", "X1 ", "患者01", "ＸＹ１", "X\\1", "X^1", "X~1", "X&1", "X|1", "X\x001", "A" * 65],
)
def test_patient_id_refuses_without_echoing_the_value(value: str) -> None:
    with pytest.raises(ValidationError) as caught:
        validate_patient_id_input(value)
    assert value.strip() == "" or value.strip() not in caught.value.message


def test_patient_id_message_for_characters() -> None:
    with pytest.raises(ValidationError) as caught:
        validate_patient_id_input("患者01")
    assert caught.value.message == PATIENT_ID_MESSAGE


def test_birth_date() -> None:
    for value in ("", "19750510", "20261025", "20240229"):
        validate_birth_date(value, TODAY)
    for value in ("20230229", "19751301", "19750532", "00000000", "1975-05-10", "197505", "１９７５０５１０"):
        with pytest.raises(ValidationError) as caught:
            validate_birth_date(value, TODAY)
        assert caught.value.message == BIRTH_DATE_FORMAT_MESSAGE
    assert BIRTH_DATE_FORMAT_MESSAGE == "生年月日を読み取れません。1975/05/14 か S50/05/14 の形で入力してください。"
    with pytest.raises(ValidationError) as caught:
        validate_birth_date("20261026", TODAY)
    assert caught.value.message == BIRTH_DATE_FUTURE_MESSAGE
    assert BIRTH_DATE_FUTURE_MESSAGE == "生年月日が今日より後です。日付を確かめてください。"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", ""), ("19750514", "19750514"), ("1975/05/14", "19750514"), ("S50/05/14", "19750514"),
     ("昭和50年5月14日", "19750514"), (" 19750514 ", "19750514")],
)
def test_cli_birth_date_accepts_yyyymmdd_and_the_screen_forms(value: str, expected: str) -> None:
    """誤りの文が示す形（1975/05/14・S50/05/14）を、CLI でも受ける."""
    assert birth_date_from_cli(value, TODAY) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [("20230229", BIRTH_DATE_FORMAT_MESSAGE), ("1975-05-14", BIRTH_DATE_FORMAT_MESSAGE),
     ("20261026", BIRTH_DATE_FUTURE_MESSAGE), ("R8/10/26", BIRTH_DATE_FUTURE_MESSAGE),
     ("H31/05/01", "生年月日が平成の範囲にありません。")],
)
def test_cli_birth_date_refuses_with_the_screen_messages(value: str, message: str) -> None:
    with pytest.raises(ValidationError) as caught:
        birth_date_from_cli(value, TODAY)
    assert caught.value.message.startswith(message)


def test_sex() -> None:
    for value in ("", "M", "F", "O"):
        validate_sex(value)
    for value in ("X", "m", "男"):
        with pytest.raises(ValidationError, match="性別"):
            validate_sex(value)


def test_validate_patient_input_checks_a_patient_made_directly() -> None:
    good = Patient(patient_id="X1", name=PersonName(alphabetic="SATO^JIRO"), birth_date="19750510", sex="M")
    validate_patient_input(good, TODAY)
    bad = Patient(patient_id="X1", name=PersonName(alphabetic="佐藤^次郎"))
    with pytest.raises(ValidationError, match="氏名（英字）は半角"):
        validate_patient_input(bad, TODAY)


def test_screen_messages_cover_the_checked_kinds() -> None:
    assert set(INPUT_MESSAGES) == {
        "patient-id", "alphabetic", "ideographic", "phonetic", "birth-date"
    }
