"""HL7 v2.3.1 のメッセージの組み立てと ACK の読み取りの試験（docs/spec/06_hl7_pir.md）."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.exceptions import AckParseError, ValidationError
from app.core.hl7 import (
    Hl7Header,
    build_adt_a08,
    build_adt_a40,
    build_orm_o01,
    escape,
    new_control_id,
    parse_ack,
    unescape,
)
from app.core.models import Order, Patient, PersonName
from app.services.order_service import OrderRequest, OrderService
from tests.conftest import TODAY

NOW = datetime(2026, 10, 24, 20, 15, 30)
HEADER = Hl7Header("RIS_EMU", "TEST_HOSPITAL", "PACS", "PACS", "P")
NAMESPACE = "RIS_EMU"
YAMADA = PersonName(
    alphabetic="YAMADA^TARO", ideographic="山田^太郎", phonetic="ヤマダ^タロウ"
)
PATIENT = Patient(patient_id="RE0000001", name=YAMADA, birth_date="19800101", sex="M")


def _segments(text: str) -> dict[str, list[str]]:
    """セグメント名 → 欄の並び（MSH は欄 1 が `|` なので、MSH-n が fields[n-1] になるよう先頭を揃える）."""
    result: dict[str, list[str]] = {}
    assert text.endswith("\r") and "\n" not in text
    for line in text.split("\r")[:-1]:
        fields = line.split("|")
        if fields[0] == "MSH":
            fields = ["MSH", "|", *fields[1:]]
        result[fields[0]] = fields
    return result


def _order(service: OrderService) -> Order:
    [order] = service.create_orders(
        OrderRequest(
            counts={"CT": 1},
            scheduled_date=TODAY,
            patient_source="roster",
            roster_patient_id="P000001",
            seed=1,
        )
    )
    return order


def test_escape_round_trips_every_delimiter() -> None:
    raw = "a|b^c~d\\e&f"
    escaped = escape(raw)
    assert escaped == "a\\F\\b\\S\\c\\R\\d\\E\\e\\T\\f"
    assert not set("|^~&") & set(escaped)
    assert unescape(escaped) == raw


@pytest.mark.parametrize("value", ["a\rb", "a\nb", "a\x0bb", "a\x1cb", "a\tb"])
def test_escape_refuses_control_characters(value: str) -> None:
    with pytest.raises(ValidationError):
        escape(value)


def test_unescape_keeps_unknown_sequences() -> None:
    assert unescape("a\\.br\\b\\X0A\\") == "a\\.br\\b\\X0A\\"


def test_control_id_fits_msh_10() -> None:
    first, second = new_control_id(NOW), new_control_id(NOW)
    assert first.startswith("261024201530") and len(first) == 20 and first != second


def test_a40_has_pid_for_the_correct_patient_and_mrg_for_the_old_one() -> None:
    message = build_adt_a40(
        HEADER,
        PATIENT,
        namespace=NAMESPACE,
        prior_patient_id="ER0001",
        prior_name=PersonName(alphabetic="UNKNOWN^MALE"),
        now=NOW,
        control_id="CTRL0000000000000001",
    )
    assert message.message_type == "ADT^A40"
    assert message.text == (
        "MSH|^~\\&|RIS_EMU|TEST_HOSPITAL|PACS|PACS|20261024201530||ADT^A40^ADT_A39"
        "|CTRL0000000000000001|P|2.3.1||||||UNICODE UTF-8\r"
        "EVN|A40|20261024201530\r"
        "PID|1||RE0000001^^^RIS_EMU^PI||YAMADA^TARO^^^^^L^A~山田^太郎^^^^^L^I"
        "~ヤマダ^タロウ^^^^^L^P||19800101|M\r"
        "MRG|ER0001^^^RIS_EMU^PI||||||UNKNOWN^MALE^^^^^L^A\r"
    )


def test_a40_requires_a_different_old_id() -> None:
    with pytest.raises(ValidationError, match="旧い患者 ID"):
        build_adt_a40(HEADER, PATIENT, namespace=NAMESPACE, prior_patient_id="", now=NOW)
    with pytest.raises(ValidationError, match="A08"):
        build_adt_a40(HEADER, PATIENT, namespace=NAMESPACE, prior_patient_id="RE0000001", now=NOW)


def test_a40_without_old_name_leaves_mrg_7_empty() -> None:
    message = build_adt_a40(HEADER, PATIENT, namespace=NAMESPACE, prior_patient_id="ER0001", now=NOW)
    mrg = _segments(message.text)["MRG"]
    assert mrg[1] == "ER0001^^^RIS_EMU^PI" and mrg[7] == ""


def test_a08_has_pv1_with_visit_number() -> None:
    message = build_adt_a08(
        HEADER, PATIENT, namespace=NAMESPACE, visit_number="V0001", patient_class="E", now=NOW
    )
    segments = _segments(message.text)
    assert message.message_type == "ADT^A08"
    assert segments["MSH"][9] == "ADT^A08^ADT_A08"
    assert segments["EVN"][1] == "A08" and segments["EVN"][2] == "20261024201530"
    assert segments["PV1"][2] == "E" and segments["PV1"][19] == "V0001^^^RIS_EMU^VN"
    assert segments["PV1"][51] == "V"
    assert "MRG" not in segments


def test_a08_needs_visit_number_or_account_number() -> None:
    with pytest.raises(ValidationError, match="PV1-19"):
        build_adt_a08(HEADER, PATIENT, namespace=NAMESPACE, now=NOW)
    message = build_adt_a08(HEADER, PATIENT, namespace=NAMESPACE, account_number="AC01", now=NOW)
    segments = _segments(message.text)
    assert segments["PID"][18] == "AC01^^^RIS_EMU^AN" and "19" not in segments["PV1"]


def test_pid_3_needs_assigning_authority() -> None:
    with pytest.raises(ValidationError, match="issuer_namespace"):
        build_adt_a08(HEADER, PATIENT, namespace="", visit_number="V1", now=NOW)


def test_patient_class_is_one_character() -> None:
    with pytest.raises(ValidationError, match="患者区分"):
        build_adt_a08(HEADER, PATIENT, namespace=NAMESPACE, visit_number="V1", patient_class="OP", now=NOW)


def test_patient_name_is_required() -> None:
    patient = Patient(patient_id="RE0000002", name=PersonName())
    with pytest.raises(ValidationError, match="PID-5"):
        build_adt_a08(HEADER, patient, namespace=NAMESPACE, visit_number="V1", now=NOW)


def test_xpn_swaps_dicom_prefix_and_suffix() -> None:
    """DICOM の PN は 姓^名^ミドル^接頭辞^接尾辞、HL7 の XPN は 姓^名^ミドル^接尾辞^接頭辞."""
    patient = Patient(patient_id="RE0000003", name=PersonName(alphabetic="DOE^JOHN^Q^DR^JR"))
    message = build_adt_a08(HEADER, patient, namespace=NAMESPACE, visit_number="V1", now=NOW)
    assert _segments(message.text)["PID"][5] == "DOE^JOHN^Q^JR^DR^^L^A"


def test_name_with_delimiters_is_restored_by_the_receiver() -> None:
    """氏名に `&`・`|`・`~` があっても、受け手が元の値に戻せる（`^` は DICOM の PN でもコンポーネントの区切り）."""
    patient = Patient(
        patient_id="RE0000004",
        name=PersonName(alphabetic="O&BRIEN|X^JOHN~JR", ideographic="山田&田中^太郎"),
    )
    message = build_adt_a08(HEADER, patient, namespace=NAMESPACE, visit_number="V|1", now=NOW)
    pid = _segments(message.text)["PID"]
    names = [rep.split("^") for rep in pid[5].split("~")]
    assert [unescape(part) for part in names[0][:2]] == ["O&BRIEN|X", "JOHN~JR"]
    assert [unescape(part) for part in names[1][:2]] == ["山田&田中", "太郎"]
    visit = _segments(message.text)["PV1"][19].split("^")
    assert unescape(visit[0]) == "V|1"
    # 区切り文字が欄の数を変えていない
    assert len(pid) == 9


def test_only_ascii_message_leaves_msh_18_empty() -> None:
    patient = Patient(patient_id="RE0000005", name=PersonName(alphabetic="YAMADA^TARO"))
    message = build_adt_a08(HEADER, patient, namespace=NAMESPACE, visit_number="V1", now=NOW)
    msh = _segments(message.text)["MSH"]
    assert len(msh) <= 13 and "UNICODE" not in message.text
    assert message.to_bytes().isascii()


def test_kanji_message_sets_msh_18_and_is_utf8() -> None:
    message = build_adt_a08(HEADER, PATIENT, namespace=NAMESPACE, visit_number="V1", now=NOW)
    assert _segments(message.text)["MSH"][18] == "UNICODE UTF-8"
    assert "山田^太郎" in message.to_bytes().decode("utf-8")


def test_header_names_are_escaped() -> None:
    header = Hl7Header("A&B", "C^D", "E|F", "G~H", "T")
    message = build_adt_a08(header, PATIENT, namespace=NAMESPACE, visit_number="V1", now=NOW)
    msh = _segments(message.text)["MSH"]
    assert [unescape(msh[n]) for n in (3, 4, 5, 6)] == ["A&B", "C^D", "E|F", "G~H"]
    assert msh[11] == "T"


def test_orm_carries_order_identifiers_unescaped(service: OrderService) -> None:
    order = _order(service)
    message = build_orm_o01(HEADER, order, visit_number=order.accession_number, now=NOW)
    segments = _segments(message.text)
    assert message.message_type == "ORM^O01"
    assert segments["MSH"][9] == "ORM^O01^ORM_O01"
    assert segments["ORC"][1] == "NW" and segments["ORC"][5] == "SC"
    start = order.scheduled_date + order.scheduled_time
    assert segments["ORC"][7] == f"^^^{start}" and segments["OBR"][27] == f"^^^{start}"
    # ADR-0003：発番した識別子は、エスケープなしでそのまま入る
    obr = segments["OBR"]
    assert obr[18] == order.accession_number
    assert obr[19] == order.requested_procedure_id
    assert obr[20] == order.scheduled_procedure_step_id
    assert segments["ORC"][3] == f"{order.accession_number}^{order.issuer_namespace}" == obr[3]
    assert len(obr[18]) <= 16
    assert obr[24] == order.modality
    assert segments["ZDS"][1] == f"{order.study_instance_uid}^RIS_EMU^Application^DICOM"
    assert segments["PID"][3] == f"{order.patient.patient_id}^^^{order.issuer_namespace}^PI"
    assert segments["PV1"][19] == f"{order.accession_number}^^^{order.issuer_namespace}^VN"
    procedure = order.procedure
    assert obr[44] == f"{procedure.code}^{procedure.name}^{procedure.coding_scheme}"
    assert obr[4] == "^".join([procedure.code, procedure.name, procedure.coding_scheme] * 2)
    assert obr[5] == "R"
    assert obr[1] == "1"


def test_orm_needs_the_issuer_namespace(service: OrderService) -> None:
    order = _order(service).model_copy(update={"issuer_namespace": ""})
    with pytest.raises(ValidationError, match="issuer_namespace"):
        build_orm_o01(HEADER, order, visit_number="V1", now=NOW)


def test_orm_needs_visit_number(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="PV1-19"):
        build_orm_o01(HEADER, _order(service), visit_number="", now=NOW)


def test_orm_escapes_free_text_fields(service: OrderService) -> None:
    order = _order(service)
    procedure = order.procedure.model_copy(update={"name": "胸部 A&B|C^D~E"})
    order = order.model_copy(update={"procedure": procedure})
    message = build_orm_o01(HEADER, order, visit_number="V1", now=NOW)
    obr = _segments(message.text)["OBR"]
    assert unescape(obr[44].split("^")[1]) == "胸部 A&B|C^D~E"
    assert len(obr) == 45


def test_orm_sends_referring_physician_in_pv1_8(service: OrderService) -> None:
    order = _order(service).model_copy(
        update={"referring_physician": PersonName(alphabetic="SUZUKI^ICHIRO", ideographic="鈴木^一郎")}
    )
    message = build_orm_o01(HEADER, order, visit_number="V1", now=NOW)
    assert _segments(message.text)["PV1"][8] == "^SUZUKI^ICHIRO"


def test_every_message_is_one_mllp_safe_block(service: OrderService) -> None:
    order = _order(service)
    for message in (
        build_adt_a08(HEADER, PATIENT, namespace=NAMESPACE, visit_number="V1", now=NOW),
        build_adt_a40(HEADER, PATIENT, namespace=NAMESPACE, prior_patient_id="ER1", now=NOW),
        build_orm_o01(HEADER, order, visit_number="V1", now=NOW),
    ):
        data = message.to_bytes()
        assert b"\x0b" not in data and b"\x1c" not in data and b"\n" not in data
        assert message.display().count("\n") == message.text.count("\r")


def test_parse_ack_accept() -> None:
    ack = parse_ack("MSH|^~\\&|PACS|PACS|RIS_EMU|TEST_HOSPITAL|20261024201531||ACK|A1|P|2.3.1\rMSA|AA|CTRL1\r")
    assert (ack.code, ack.control_id, ack.text, ack.error) == ("AA", "CTRL1", "", "")


def test_parse_ack_reject_with_text_and_err() -> None:
    raw = (
        "MSH|^~\\&|PACS|PACS|RIS_EMU|X|20261024201531||ACK|A2|P|2.3.1\r"
        "MSA|AR|CTRL1|unknown patient \\F\\ id\r"
        "ERR|PID^1^3\r"
    )
    ack = parse_ack(raw.encode("utf-8"))
    assert (ack.code, ack.text, ack.error) == ("AR", "unknown patient | id", "PID^1^3")


def test_parse_ack_accepts_lf_separators() -> None:
    ack = parse_ack("MSH|^~\\&|A|B|C|D|20261024||ACK|1|P|2.3.1\nMSA|AE|CTRL9\n")
    assert (ack.code, ack.control_id) == ("AE", "CTRL9")


@pytest.mark.parametrize(
    "raw",
    ["", "PID|1\r", "MSH|^~\\&|A|B|C|D|20261024||ACK|1|P|2.3.1\r", "MSH|ab|A\rMSA|AA|1\r"],
)
def test_parse_ack_refuses_bad_input(raw: str) -> None:
    with pytest.raises(AckParseError):
        parse_ack(raw)
