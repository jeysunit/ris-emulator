"""Specific Character Set で書けない字の確かめ（docs/spec/02_mwl_scp.md 5 章）.

pydicom は書けない字を黙って `?` に置き換えるので、予約を保存する前に確かめる。
Pure な処理。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

# 文字コードの影響を受ける VR（PS3.5 6.1.2.3）
TEXT_VRS = frozenset({"SH", "LO", "ST", "LT", "UT", "PN", "UC"})
_ASCII_MAX = 0x7F
_HALFWIDTH_KATAKANA_MIN = 0xA1
_HALFWIDTH_KATAKANA_MAX = 0xDF
_JIS_X_0208_ESCAPES = (b"\x1b$B", b"\x1b$@")


def find_unencodable(ds: Dataset) -> list[tuple[str, str]]:
    """Specific Character Set で書けない字を (属性, 字の並び) で返す。無ければ空."""
    terms = _character_set_terms(ds)
    problems: list[tuple[str, str]] = []
    for attribute, text in _iter_text_values(ds, prefix=""):
        chars = unencodable_chars(text, terms)
        if chars:
            problems.append((attribute, "".join(chars)))
    return problems


def unencodable_chars(value: str, terms: Sequence[str]) -> list[str]:
    """`terms` のどれでも書けない字を、出た順に重ねずに返す."""
    found: list[str] = []
    for char in value:
        if char in found or ord(char) <= _ASCII_MAX or any(_accepts(t, char) for t in terms):
            continue
        found.append(char)
    return found


def _accepts(term: str, char: str) -> bool:
    if term == "ISO_IR 192":
        return True
    if term == "ISO 2022 IR 87":
        try:
            encoded = char.encode("iso2022_jp")
        except UnicodeEncodeError:
            return False
        return any(escape in encoded for escape in _JIS_X_0208_ESCAPES)
    if term == "ISO 2022 IR 13":
        try:
            encoded = char.encode("shift_jis")
        except UnicodeEncodeError:
            return False
        return len(encoded) == 1 and _HALFWIDTH_KATAKANA_MIN <= encoded[0] <= _HALFWIDTH_KATAKANA_MAX
    return False


def _character_set_terms(ds: Dataset) -> list[str]:
    value = ds.get("SpecificCharacterSet")
    if value is None:
        return []
    if isinstance(value, (list, MultiValue)):
        return [str(term).strip() for term in value]
    return [str(value).strip()]


def _iter_text_values(ds: Dataset, prefix: str) -> Iterator[tuple[str, str]]:
    for element in ds:
        name = f"{prefix}{element.keyword or element.tag}"
        if element.VR == "SQ":
            for item in element.value or []:
                yield from _iter_text_values(item, prefix=f"{name}>")
            continue
        if element.VR not in TEXT_VRS or element.value is None:
            continue
        values = element.value if isinstance(element.value, (list, MultiValue)) else [element.value]
        for value in values:
            yield name, str(value)
