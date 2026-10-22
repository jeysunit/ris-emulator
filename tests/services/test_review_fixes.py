"""公開前のレビューで直した点の試験（文字コード・名簿・日付・欠番・環境変数・Return Key）."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydicom.dataset import Dataset

from app.core.charset import find_unencodable, unencodable_chars
from app.core.exceptions import ConfigurationError, ValidationError
from app.core.models import CharacterSet
from app.mwl.server import find_worklist
from app.services.config import AppConfig, load_config
from app.services.order_service import OrderRequest, OrderService, parse_date_option
from app.services.roster import load_roster
from app.services.store import OrderStore
from tests.conftest import ROOT, TODAY

ROSTER_TEMPLATE = """\
patients:
  - patient_id: "X000001"
    patient_name:
      alphabetic: "TAKAHASHI^ICHIRO"
      ideographic: "{ideographic}"
      phonetic: "タカハシ^イチロウ"
    birth_date: "19800101"
    sex: "M"
"""


def _service_with_roster(config: AppConfig, tmp_path: Path, ideographic: str) -> OrderService:
    roster = tmp_path / "roster.yaml"
    roster.write_text(ROSTER_TEMPLATE.format(ideographic=ideographic), encoding="utf-8")
    orders = config.orders.model_copy(update={"roster_path": str(roster)})
    changed = config.model_copy(update={"orders": orders})
    return OrderService(changed, OrderStore(Path(config.database)), today=lambda: TODAY)


def _roster_request(character_set: CharacterSet) -> OrderRequest:
    return OrderRequest(
        counts={"CT": 1},
        scheduled_date=TODAY,
        patient_source="roster",
        character_set=character_set,
        seed=1,
    )


@pytest.mark.parametrize(
    ("ideographic", "character_set", "bad"),
    [
        ("髙橋^一郎", CharacterSet.JIS, "髙"),
        ("髙橋^一郎", CharacterSet.JIS_KANA, "髙"),
        ("𠮷田^一郎", CharacterSet.JIS, "𠮷"),
    ],
)
def test_unencodable_name_is_rejected(
    config: AppConfig, tmp_path: Path, ideographic: str, character_set: CharacterSet, bad: str
) -> None:
    service = _service_with_roster(config, tmp_path, ideographic)
    with pytest.raises(ValidationError) as excinfo:
        service.create_orders(_roster_request(character_set))
    message = str(excinfo.value)
    assert "PatientName" in message and bad in message
    assert service.list_orders() == []


def test_unencodable_error_uses_character_set_label(config: AppConfig, tmp_path: Path) -> None:
    """エラーの文は文字コードを表示の名前で書き、値を `\\` でつないだ文字列を出さない."""
    service = _service_with_roster(config, tmp_path, "髙橋^一郎")
    with pytest.raises(ValidationError) as excinfo:
        service.create_orders(_roster_request(CharacterSet.JIS))
    message = str(excinfo.value)
    assert "日本語（JIS X 0208、ISO 2022 IR 87）で書けません" in message
    assert "Unicode（UTF-8、ISO_IR 192）にするか" in message
    assert "\\" not in message


def test_unencodable_name_is_fine_in_utf8(config: AppConfig, tmp_path: Path) -> None:
    service = _service_with_roster(config, tmp_path, "髙橋^一郎")
    orders = service.create_orders(_roster_request(CharacterSet.UTF8))
    assert orders[0].patient.name.ideographic == "髙橋^一郎"


def test_rejected_order_does_not_use_a_number(config: AppConfig, tmp_path: Path) -> None:
    """断った回は連番を使わない（欠番を作らない）."""
    service = _service_with_roster(config, tmp_path, "髙橋^一郎")
    with pytest.raises(ValidationError):
        service.create_orders(_roster_request(CharacterSet.JIS))
    orders = service.create_orders(_roster_request(CharacterSet.UTF8))
    assert orders[0].accession_number == "RE202610210001"


def test_find_unencodable_reports_attribute_and_chars() -> None:
    ds = Dataset()
    ds.SpecificCharacterSet = ["", "ISO 2022 IR 87"]
    ds.PatientName = "TAKAHASHI^ICHIRO=髙橋^一郎"
    ds.RequestingService = "内科"
    sps = Dataset()
    sps.ScheduledProcedureStepDescription = "𠮷"
    ds.ScheduledProcedureStepSequence = [sps]
    assert find_unencodable(ds) == [
        ("PatientName", "髙"),
        ("ScheduledProcedureStepSequence>ScheduledProcedureStepDescription", "𠮷"),
    ]
    assert unencodable_chars("ｱｲｳ", ["ISO 2022 IR 13", "ISO 2022 IR 87"]) == []
    assert unencodable_chars("ｱ", ["", "ISO 2022 IR 87"]) == ["ｱ"]
    assert unencodable_chars("髙𠮷", ["ISO_IR 192"]) == []


@pytest.mark.parametrize(
    "ideographic",
    ["田中=博", "田中\\\\博", "あ" * 65],
)
def test_roster_name_validator(tmp_path: Path, ideographic: str) -> None:
    roster = tmp_path / "roster.yaml"
    roster.write_text(ROSTER_TEMPLATE.format(ideographic=ideographic), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="ideographic"):
        load_roster(roster)


def test_scheduled_date_range() -> None:
    with pytest.raises(ValidationError, match="1900"):
        parse_date_option("18991231", TODAY)
    with pytest.raises(ValidationError, match="1900"):
        parse_date_option("00010101", TODAY)
    with pytest.raises(ValidationError, match="9999"):
        parse_date_option("tomorrow", date(9999, 12, 31))
    assert parse_date_option("99991231", TODAY) == date(9999, 12, 31)
    with pytest.raises(Exception):  # pydantic の ValidationError
        OrderRequest(counts={"CT": 1}, scheduled_date=date(1800, 1, 1))


def test_last_day_of_9999_does_not_overflow(service: OrderService) -> None:
    from datetime import time

    with pytest.raises(ValidationError, match="その日のうち"):
        service.create_orders(
            OrderRequest(
                counts={"CT": 3},
                scheduled_date=date(9999, 12, 31),
                start_time=time(23, 50),
                interval_minutes=10,
            )
        )
    orders = service.create_orders(
        OrderRequest(counts={"CT": 1}, scheduled_date=date(9999, 12, 31), seed=1)
    )
    assert orders[0].scheduled_date == "99991231"


def test_bind_addresses_from_environment() -> None:
    path = ROOT / "config" / "app_config.yaml"
    config = load_config(
        path, {"RIS_WEB_BIND_ADDRESS": "0.0.0.0", "RIS_MWL_BIND_ADDRESS": "0.0.0.0"}
    )
    assert config.web.bind_address == "0.0.0.0"
    assert config.mwl.bind_address == "0.0.0.0"
    plain = load_config(path, {})
    assert plain.web.bind_address == "127.0.0.1" and plain.mwl.bind_address == "127.0.0.1"


def test_type2_return_keys_do_not_warn(
    config: AppConfig, store: OrderStore, service: OrderService
) -> None:
    """Table K.6-1 の Return Key Type 2 を求めても FF01 にしない."""
    service.create_orders(OrderRequest(counts={"MR": 1}, scheduled_date=TODAY, seed=1))
    request = Dataset()
    request.PatientID = ""
    for keyword in (
        "PregnancyStatus",
        "PatientTransportArrangements",
        "SpecialNeeds",
        "ReferencedPatientSequence",
        "ConfidentialityConstraintOnPatientDataDescription",
        "AdmissionID",
        "CurrentPatientLocation",
        "PatientState",
        "MedicalAlerts",
        "Allergies",
    ):
        setattr(request, keyword, [] if keyword.endswith("Sequence") else None)
    status, responses = find_worklist(request, store, config.mwl)
    assert status == 0x0000
    assert [pending for pending, _ in responses] == [0xFF00]
