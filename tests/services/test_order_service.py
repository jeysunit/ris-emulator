"""予約の作成・保存・状態の変更の試験."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from app.core.exceptions import ConfigurationError, OrderNotFoundError, ValidationError
from app.core.models import CharacterSet, OrderStatus
from app.services.config import load_config
from app.services.order_service import (
    OrderRequest,
    OrderService,
    parse_count_spec,
    parse_date_option,
    parse_time_option,
)
from app.services.roster import load_roster

from tests.conftest import ROOT, TODAY


def _request(**values: object) -> OrderRequest:
    base: dict[str, object] = {"counts": {"CT": 3, "MR": 1}, "scheduled_date": TODAY, "seed": 1}
    base.update(values)
    return OrderRequest(**base)


def test_create_ct3_mr1(service: OrderService) -> None:
    orders = service.create_orders(_request())
    assert [order.modality for order in orders] == ["CT", "CT", "CT", "MR"]
    assert [order.accession_number for order in orders] == [
        "RE202610210001",
        "RE202610210002",
        "RE202610210003",
        "RE202610210004",
    ]
    assert orders[0].requested_procedure_id == "RP202610210001"
    assert orders[0].scheduled_procedure_step_id == "SPS202610210001"
    # 装置ごとに 09:00 から 15 分おき
    assert [order.scheduled_time for order in orders] == ["090000", "091500", "093000", "090000"]
    assert {order.scheduled_station_ae_title for order in orders[:3]} == {"DTG_CT01"}
    assert orders[3].scheduled_station_ae_title == "DTG_MR01"
    assert len({order.study_instance_uid for order in orders}) == 4
    assert all(order.study_instance_uid.startswith("2.25.") for order in orders)
    assert len({order.patient.patient_id for order in orders}) == 4
    for order in orders:
        assert order.patient.patient_id.startswith("RE")
        assert order.patient.name.ideographic and order.patient.name.phonetic
        assert order.status is OrderStatus.SCHEDULED
        assert order.character_set is CharacterSet.UTF8
        assert len(order.accession_number) <= 16


def test_numbers_continue_across_requests(service: OrderService) -> None:
    service.create_orders(_request(counts={"CT": 2}))
    second = service.create_orders(_request(counts={"CR": 1}))
    assert second[0].accession_number == "RE202610210003"


def test_seed_makes_same_patients(config, tmp_path: Path) -> None:
    from app.services.store import OrderStore

    first = OrderService(config, OrderStore(tmp_path / "a.sqlite3"), today=lambda: TODAY)
    second = OrderService(config, OrderStore(tmp_path / "b.sqlite3"), today=lambda: TODAY)
    a = first.create_orders(_request(seed=42))
    b = second.create_orders(_request(seed=42))
    assert [o.patient for o in a] == [o.patient for o in b]


def test_roster_patients(service: OrderService) -> None:
    roster_ids = {patient.patient_id for patient in load_roster(ROOT / "data" / "patients_sample.yaml")}
    orders = service.create_orders(_request(patient_source="roster", counts={"CT": 5}))
    assert {order.patient.patient_id for order in orders} <= roster_ids
    tanaka = next(
        (o.patient for o in orders if o.patient.patient_id == "P000001"),
        None,
    )
    if tanaka is not None:
        assert tanaka.size_m == 1.72


def test_overrides(service: OrderService) -> None:
    orders = service.create_orders(
        _request(
            counts={"CT": 2},
            start_time=time(13, 0),
            interval_minutes=30,
            station_ae_title="CT_OTHER",
            department="救急科",
            character_set=CharacterSet.JIS_KANA,
        )
    )
    assert [order.scheduled_time for order in orders] == ["130000", "133000"]
    assert {order.scheduled_station_ae_title for order in orders} == {"CT_OTHER"}
    assert {order.requesting_service for order in orders} == {"救急科"}
    assert {order.character_set for order in orders} == {CharacterSet.JIS_KANA}


def test_unknown_modality_is_rejected(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="設定に無いモダリティ"):
        service.create_orders(_request(counts={"XA": 1}))


def test_schedule_must_fit_in_the_day(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="その日のうち"):
        service.create_orders(_request(counts={"CT": 3}, start_time=time(23, 30)))


def test_bad_station_ae_title(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="AE タイトル"):
        service.create_orders(_request(station_ae_title="TOO_LONG_AE_TITLE_X"))


@pytest.mark.parametrize("department", ["科" * 65, "内科\\外科", "内科\n"])
def test_bad_department_is_rejected_before_numbering(service: OrderService, department: str) -> None:
    with pytest.raises(ValidationError, match="依頼科"):
        service.create_orders(_request(department=department))
    # 番号を使っていない
    assert service.create_orders(_request(counts={"CT": 1}))[0].accession_number == "RE202610210001"


def test_status_change_and_listing(service: OrderService) -> None:
    orders = service.create_orders(_request())
    changed = service.set_status(orders[0].accession_number, OrderStatus.COMPLETED)
    assert changed.status is OrderStatus.COMPLETED
    assert service.get(orders[0].accession_number).status is OrderStatus.COMPLETED
    scheduled = service.list_orders(statuses=[OrderStatus.SCHEDULED])
    assert len(scheduled) == 3
    assert len(service.list_orders(modality="MR")) == 1
    assert service.list_orders(date_from="20261022") == []
    with pytest.raises(OrderNotFoundError):
        service.set_status("NOPE", OrderStatus.CANCELLED)


def test_parse_helpers() -> None:
    assert parse_count_spec("ct=3") == ("CT", 3)
    assert parse_count_spec("MR:2") == ("MR", 2)
    assert parse_count_spec("CR") == ("CR", 1)
    with pytest.raises(ValidationError):
        parse_count_spec("CT=0")
    with pytest.raises(ValidationError):
        parse_count_spec("CT=x")
    assert parse_date_option("today", TODAY) == TODAY
    assert parse_date_option("tomorrow", TODAY) == date(2026, 10, 22)
    assert parse_date_option("20261101", TODAY) == date(2026, 11, 1)
    with pytest.raises(ValidationError):
        parse_date_option("2026/11/01", TODAY)
    assert parse_time_option("09:30") == time(9, 30)
    with pytest.raises(ValidationError):
        parse_time_option("25:00")


def test_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("orders:\n  modalities: {}\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="orders.modalities"):
        load_config(bad)
    statuses = tmp_path / "statuses.yaml"
    statuses.write_text(
        "mwl:\n  statuses: [completed]\norders:\n  modalities:\n    CT:\n"
        "      station_ae_titles: [CT1]\n      procedures: [{code: C1, name: n}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="must not include completed"):
        load_config(statuses)


def test_roster_errors(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("patients: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="non-empty"):
        load_roster(empty)
    bad = tmp_path / "bad.yaml"
    bad.write_text("patients:\n  - patient_id: P1\n    patient_name: {}\n    sex: X\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="#1"):
        load_roster(bad)
