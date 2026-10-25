"""手で入れた患者の入力の確かめ（docs/spec/01_orders.md 3.4）."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import ValidationError
from app.core.models import Patient, PersonName
from app.core.patient_input import (
    ALPHABETIC_MESSAGE,
    BIRTH_DATE_FUTURE_MESSAGE,
    IDEOGRAPHIC_MESSAGE,
    INPUT_MESSAGES,
    PATIENT_ID_MESSAGE,
    check_name_component,
    check_name_group,
    check_phonetic_group,
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


@pytest.mark.parametrize("value", ["佐藤^次郎", "高橋^あ", "ヤマダ", "佐藤　次郎", "佐藤^JIRO"])
def test_ideographic_group_accepts_jis_x_0208(value: str) -> None:
    assert check_name_group("ideographic", "漢字", value) == ""


@pytest.mark.parametrize("value", ["髙橋^太郎", "ﾔﾏﾀﾞ", "佐藤😀", "𠮷田"])
def test_ideographic_group_refuses_unrepresentable_characters(value: str) -> None:
    message = check_name_group("ideographic", "漢字", value)
    assert message == IDEOGRAPHIC_MESSAGE
    assert not any(char in message for char in "髙橋太郎😀𠮷田")


def test_phonetic_group_is_not_restricted_yet() -> None:
    """ひらがな・カタカナ・半角カナのどれを許すかは未決。今は種類を見ない."""
    for value in ("さとう^じろう", "サトウ^ジロウ", "ｻﾄｳ^ｼﾞﾛｳ", "Sato"):
        assert check_phonetic_group(value) == ""
        assert check_name_group("phonetic", "かな", value) == ""


def test_phonetic_group_still_gets_common_checks() -> None:
    assert "64 字以内" in check_name_group("phonetic", "かな", "あ" * 65)
    assert check_name_group("phonetic", "かな", "あ\\い")
    assert check_name_group("phonetic", "かな", "あ\x1bい")
    assert check_name_group("phonetic", "かな", "あ=い")


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
    with pytest.raises(ValidationError, match="氏名（漢字）に使えない字"):
        validate_person_name(PersonName(alphabetic="TAKAHASHI", ideographic="髙橋"))


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
        with pytest.raises(ValidationError, match="暦にある日付"):
            validate_birth_date(value, TODAY)
    with pytest.raises(ValidationError) as caught:
        validate_birth_date("20261026", TODAY)
    assert caught.value.message == BIRTH_DATE_FUTURE_MESSAGE


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
    assert set(INPUT_MESSAGES) == {"patient-id", "alphabetic", "ideographic", "birth-date"}
