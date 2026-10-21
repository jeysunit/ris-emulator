"""C-FIND の要求の照合（docs/spec/02_mwl_scp.md 3 章）.

出典は DICOM PS3.4 C.2.2.2（Attribute Matching）と K.6-1（Remark / Matching Type）。
Pure な処理。値は pydicom が Specific Character Set で戻した Python の文字列で比べる。
"""

from __future__ import annotations

from collections.abc import Iterable

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

from .mwl_dataset import NON_KEY_TAGS

WILDCARD_CHARS = frozenset("*?")
_RANGE_VRS = frozenset({"DA", "TM", "DT"})
_START_DATE = 0x00400002
_START_TIME = 0x00400003
_TIME_DIGITS = 6
_FRACTION_DIGITS = 6
_TIME_MAX = "235959"


def has_matching_keys(request: Dataset) -> bool:
    """要求に照合の属性が1つでもあるか（無ければ一致なし。PS3.4 K.4.1.3.1）."""
    return any(element.tag not in NON_KEY_TAGS for element in request)


def matches(full: Dataset, request: Dataset) -> bool:
    """`full`（予約の Dataset）が要求のすべての照合の条件に合うか.

    この SCP が持たない属性の条件は無視する（Return Key としてだけ扱う）。
    """
    combined = _is_date_time_period(request)
    for element in request:
        if element.tag in NON_KEY_TAGS or element.tag.is_private:
            continue
        if combined and element.tag in (_START_DATE, _START_TIME):
            continue
        if element.tag not in full:
            continue
        target = full[element.tag]
        if element.VR == "SQ":
            if not _sequence_matches(target.value, element.value):
                return False
            continue
        if not _value_matches(element.VR, element.value, target.value):
            return False
    return not combined or _period_matches(full, request)


def _sequence_matches(targets: Iterable[Dataset], requested: Iterable[Dataset]) -> bool:
    """Sequence Matching：要求の項目の条件に合う項目が1つでもあれば一致（PS3.4 C.2.2.2.6）."""
    request_items = list(requested or [])
    if not request_items or not _has_values(request_items[0]):
        return True
    return any(matches(item, request_items[0]) for item in targets or [])


def _has_values(item: Dataset) -> bool:
    for element in item:
        if element.VR == "SQ":
            if any(_has_values(child) for child in element.value or []):
                return True
        elif not _is_empty(element.value):
            return True
    return False


def _value_matches(vr: str, query: object, value: object) -> bool:
    if _is_empty(query):
        return True  # Universal Matching
    if vr == "UI":
        return _text(value) in _values(query)  # List of UID Matching
    if vr in _RANGE_VRS:
        # 予定の日と時刻が両方とも範囲のときは _period_matches で組で比べる
        return _range_matches(_text(query), _text(value), vr)
    query_text = _text(query)
    value_text = _text(value)
    if vr == "PN":
        return person_name_matches(query_text, value_text)
    if WILDCARD_CHARS & set(query_text):
        return wildcard_matches(query_text, value_text, ignore_case=False)
    return query_text == value_text


def person_name_matches(query: str, value: str) -> bool:
    """PN の照合。大文字と小文字を区別しない（PS3.4 C.2.2.2.1.1 の選べる形）.

    要求に `=` が無ければ、英字・漢字・かなのどれかのコンポーネントグループに合えば一致。
    `=` があれば、要求の空でないコンポーネントグループごとに同じ番目のものと比べる。
    """
    value_groups = value.split("=")
    if "=" not in query:
        return wildcard_matches(query, value, ignore_case=True) or any(
            wildcard_matches(query, group, ignore_case=True) for group in value_groups
        )
    for index, group in enumerate(query.split("=")):
        if not group:
            continue
        target = value_groups[index] if index < len(value_groups) else ""
        if not wildcard_matches(group, target, ignore_case=True):
            return False
    return True


def wildcard_matches(pattern: str, value: str, *, ignore_case: bool) -> bool:
    """`*`（0 字以上）と `?`（1 字）の照合（PS3.4 C.2.2.2.4）.

    正規表現にせず、最後の `*` まで戻る方法で比べる（手間は長さの積で抑えられる）。
    """
    if ignore_case:
        pattern, value = pattern.casefold(), value.casefold()
    p = v = 0
    star = -1
    resume = 0
    while v < len(value):
        if p < len(pattern) and pattern[p] in ("?", value[v]) and pattern[p] != "*":
            p += 1
            v += 1
        elif p < len(pattern) and pattern[p] == "*":
            star, resume = p, v
            p += 1
        elif star >= 0:
            p = star + 1
            resume += 1
            v = resume
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def _range_matches(query: str, value: str, vr: str) -> bool:
    """Single Value Matching と Range Matching（`a-b`・`-b`・`a-`。PS3.4 C.2.2.2.5）."""
    if "-" not in query:
        return _normalize(value, vr) == _normalize(query, vr)
    low, _, high = query.partition("-")
    if not value:
        return False
    current = _normalize(value, vr)
    if low and current < _normalize(low, vr):
        return False
    return not (high and current > _normalize(high, vr, upper=True))


def _is_date_time_period(request: Dataset) -> bool:
    """予定の日と時刻が両方とも範囲で来たか（Scheduled Procedure Step の項目の中）."""
    return "-" in _element_text(request, _START_DATE) and "-" in _element_text(request, _START_TIME)


def _period_matches(full: Dataset, request: Dataset) -> bool:
    """予定の日と時刻を、日時の期間として比べる（PS3.4 K.6-1 の Scheduled Procedure Step Start Time の Remark）.

    例：日付 `20261005-20261007` と時刻 `1000-1800` は、10/5 10:00 から 10/7 18:00 まで。
    """
    date_low, _, date_high = _element_text(request, _START_DATE).partition("-")
    time_low, _, time_high = _element_text(request, _START_TIME).partition("-")
    date_value = _element_text(full, _START_DATE)
    if not date_value:
        return False
    current = date_value + _normalize(_element_text(full, _START_TIME), "TM")
    low = (date_low + _normalize(time_low or "000000", "TM")) if date_low else ""
    high = (date_high + _normalize(time_high or _TIME_MAX, "TM", upper=True)) if date_high else ""
    if low and current < low:
        return False
    return not (high and current > high)


def _element_text(ds: Dataset, tag: int) -> str:
    return _text(ds[tag].value) if tag in ds else ""


def _normalize(value: str, vr: str, upper: bool = False) -> str:
    """TM は `HHMMSS.ffffff` にそろえる（`10` → `100000.000000`、上限は `105959.999999`）."""
    value = value.strip()
    if vr != "TM":
        return value
    whole, _, fraction = value.partition(".")
    digits = whole.replace(":", "")[:_TIME_DIGITS]
    fraction = fraction[:_FRACTION_DIGITS]
    if upper:
        digits = digits + _TIME_MAX[len(digits) :]
        return f"{digits}.{fraction.ljust(_FRACTION_DIGITS, '9')}"
    return f"{digits.ljust(_TIME_DIGITS, '0')}.{fraction.ljust(_FRACTION_DIGITS, '0')}"


def _values(value: object) -> list[str]:
    if isinstance(value, (list, MultiValue)):
        return [str(v) for v in value]
    return [v for v in str(value).split("\\")]


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, MultiValue)):
        return "\\".join(str(v) for v in value)
    return str(value)


def _is_empty(value: object) -> bool:
    return value is None or _text(value) == ""
