"""予約の作成・保存・状態の変更の試験."""

from __future__ import annotations

import re
from datetime import date, time
from pathlib import Path

import pytest

from app.core.exceptions import (
    ConfigurationError,
    InvalidTransitionError,
    OrderNotFoundError,
    ValidationError,
)
from app.core.models import CharacterSet, OrderStatus
from app.services.config import AppConfig, Station, load_config
from app.services.order_service import (
    OrderRequest,
    OrderService,
    parse_count_spec,
    parse_date_option,
    parse_time_option,
)
from app.services.roster import load_roster
from app.services.store import OrderStore

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
    assert {order.scheduled_station_ae_title for order in orders[:3]} == {"CT01"}
    assert orders[3].scheduled_station_ae_title == "MR01"
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


def _two_ct_stations(config: AppConfig, store: OrderStore) -> OrderService:
    """CT の台帳に CT1号機・CT2号機を並べた設定（docs/spec/01_orders.md 1 章）."""
    ct = config.orders.modalities["CT"].model_copy(
        update={
            "stations": [
                Station(name="CT1号機", ae_title="CT01", station_name="CT01"),
                Station(name="CT2号機", ae_title="CT02", station_name="CT02"),
            ]
        }
    )
    orders = config.orders.model_copy(
        update={"modalities": {**config.orders.modalities, "CT": ct}}
    )
    return OrderService(config.model_copy(update={"orders": orders}), store, today=lambda: TODAY)


def test_overrides(config: AppConfig, store: OrderStore) -> None:
    service = _two_ct_stations(config, store)
    orders = service.create_orders(
        _request(
            counts={"CT": 2},
            start_time=time(13, 0),
            interval_minutes=30,
            stations={"CT": "CT2号機"},
            department="救急科",
            character_set=CharacterSet.JIS_KANA,
        )
    )
    assert [order.scheduled_time for order in orders] == ["130000", "133000"]
    assert {order.scheduled_station_ae_title for order in orders} == {"CT02"}
    assert {order.scheduled_station_name for order in orders} == {"CT02"}
    assert {order.scheduled_station_label for order in orders} == {"CT2号機"}
    assert {order.requesting_service for order in orders} == {"救急科"}
    assert {order.character_set for order in orders} == {CharacterSet.JIS_KANA}


def test_stations_rotate_when_not_chosen(config: AppConfig, store: OrderStore) -> None:
    orders = _two_ct_stations(config, store).create_orders(_request(counts={"CT": 3}))
    assert [order.scheduled_station_ae_title for order in orders] == ["CT01", "CT02", "CT01"]
    assert [order.scheduled_station_label for order in orders] == ["CT1号機", "CT2号機", "CT1号機"]


def test_unknown_modality_is_rejected(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="設定に無いモダリティ"):
        service.create_orders(_request(counts={"XA": 1}))


def test_schedule_must_fit_in_the_day(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="その日のうち"):
        service.create_orders(_request(counts={"CT": 3}, start_time=time(23, 30)))


@pytest.mark.parametrize(
    ("stations", "message"),
    [
        ({"CT": "CT9号機"}, "CT の台帳に無い装置です: CT9号機"),
        ({"CT": "MR1号機"}, "CT の台帳に無い装置です: MR1号機"),
        ({"MR": "MR1号機"}, "件数を指定していないモダリティの装置です"),
    ],
)
def test_bad_station_is_rejected(
    service: OrderService, stations: dict[str, str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        service.create_orders(_request(counts={"CT": 1}, stations=stations))
    assert service.list_orders() == []


def test_cli_station_names(service: OrderService) -> None:
    assert service.stations_by_name(["CT1号機", "MR1号機"], ["CT", "MR"]) == {
        "CT": "CT1号機",
        "MR": "MR1号機",
    }
    with pytest.raises(ValidationError, match="台帳: CT1号機"):
        service.stations_by_name(["CT9号機"], ["CT"])
    with pytest.raises(ValidationError, match="1つだけ"):
        service.stations_by_name(["CT1号機", "CT1号機"], ["CT"])


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


def test_final_status_cannot_change(service: OrderService) -> None:
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    completed = service.set_status(order.accession_number, OrderStatus.COMPLETED)
    for status in (OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED):
        with pytest.raises(InvalidTransitionError, match="完了の予約は"):
            service.set_status(order.accession_number, status)
    stored = service.get(order.accession_number)
    assert stored.status is OrderStatus.COMPLETED
    assert stored.updated_at == completed.updated_at


def test_in_progress_can_go_back_to_scheduled(service: OrderService) -> None:
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    service.set_status(order.accession_number, OrderStatus.IN_PROGRESS)
    back = service.set_status(order.accession_number, OrderStatus.SCHEDULED)
    assert back.status is OrderStatus.SCHEDULED


def test_same_status_is_a_no_op(service: OrderService) -> None:
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    cancelled = service.set_status(order.accession_number, OrderStatus.CANCELLED)
    again = service.set_status(order.accession_number, OrderStatus.CANCELLED)
    assert again.status is OrderStatus.CANCELLED
    assert again.updated_at == cancelled.updated_at
    assert service.get(order.accession_number).updated_at == cancelled.updated_at


def test_transition_is_checked_against_the_stored_state(service: OrderService) -> None:
    """取消が先に保存されたら、後から届いた予定への変更は断る（読んだ時点の状態で判断しない）."""
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    service.set_status(order.accession_number, OrderStatus.IN_PROGRESS)
    other = OrderService(service.config, store=type(service.store)(service.store.path))
    other.set_status(order.accession_number, OrderStatus.CANCELLED)
    with pytest.raises(InvalidTransitionError):
        service.set_status(order.accession_number, OrderStatus.SCHEDULED)
    assert service.get(order.accession_number).status is OrderStatus.CANCELLED


def test_mpps_and_order_are_written_together(service: OrderService) -> None:
    """MPPS の記録が失敗したら、予約の状態の変更も残らない（1つのトランザクション）."""
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    steps = [(order.accession_number, order.scheduled_procedure_step_id)]
    with pytest.raises(TypeError):
        service.store.create_mpps("1.2.3", steps, {"bad": object()})
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED
    assert service.list_mpps(order.accession_number) == []
    result = service.store.create_mpps("1.2.3", steps, {})
    assert result.linked == result.changed == [order.accession_number]
    assert service.get(order.accession_number).status is OrderStatus.IN_PROGRESS


def test_mpps_needs_both_identifiers(service: OrderService) -> None:
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    cases = [
        [(order.accession_number, "SPS_OTHER")],
        [("RE_OTHER", order.scheduled_procedure_step_id)],
        [(order.accession_number, "")],
    ]
    for index, steps in enumerate(cases, start=1):
        assert service.store.create_mpps(f"1.2.{index}", steps, {}).linked == []
    assert service.get(order.accession_number).status is OrderStatus.SCHEDULED


def test_discontinued_only_from_in_progress(service: OrderService) -> None:
    order = service.create_orders(_request(counts={"CT": 1}))[0]
    with pytest.raises(InvalidTransitionError, match="予定の予約は中止に変更できません"):
        service.set_status(order.accession_number, OrderStatus.DISCONTINUED)
    service.set_status(order.accession_number, OrderStatus.IN_PROGRESS)
    discontinued = service.set_status(order.accession_number, OrderStatus.DISCONTINUED)
    assert discontinued.status is OrderStatus.DISCONTINUED
    with pytest.raises(InvalidTransitionError, match="中止の予約は予定に変更できません"):
        service.set_status(order.accession_number, OrderStatus.SCHEDULED)


def test_mwl_statuses_must_not_include_discontinued(tmp_path: Path) -> None:
    raw = (ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8")
    changed = raw.replace(
        'statuses: ["scheduled", "in_progress"]', 'statuses: ["scheduled", "discontinued"]'
    )
    assert changed != raw
    path = tmp_path / "app_config.yaml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="discontinued"):
        load_config(path)


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
        "      stations: [{name: CT1号機, ae_title: CT1}]\n      procedures: [{code: C1, name: n}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="must not include completed"):
        load_config(statuses)


def _config_with_ct(tmp_path: Path, ct: str) -> Path:
    path = tmp_path / "app_config.yaml"
    path.write_text(
        f"orders:\n  modalities:\n    CT:\n{ct}      procedures: [{{code: C1, name: n}}]\n"
        "    MR:\n      stations: [{name: MR1号機, ae_title: MR01}]\n"
        "      procedures: [{code: M1, name: n}]\n",
        encoding="utf-8",
    )
    return path


def test_station_registry_is_loaded(tmp_path: Path) -> None:
    path = _config_with_ct(
        tmp_path,
        "      stations:\n"
        "        - {name: CT1号機, ae_title: CT01, station_name: CT01}\n"
        "        - {name: CT2号機, ae_title: CT02, station_name: CT02}\n",
    )
    stations = load_config(path).orders.modalities["CT"].stations
    assert [(s.name, s.ae_title, s.station_name) for s in stations] == [
        ("CT1号機", "CT01", "CT01"),
        ("CT2号機", "CT02", "CT02"),
    ]


@pytest.mark.parametrize(
    ("ct", "message"),
    [
        (
            "      stations: [{name: CT1号機, ae_title: CT_AE_TITLE_17CHR}]\n",
            "orders.modalities.CT.stations.0.ae_title",
        ),
        ("      stations: [{name: CT1号機, ae_title: 'CT\\\\01'}]\n", "ae_title"),
        ("      stations: [{name: CT1号機, ae_title: CT01, station_name: STATION_NAME_17CH}]\n", "station_name"),
        ("      stations: [{name: CT1号機, ae_title: CT01, station_name: 'A\\\\B'}]\n", "station_name"),
        ("      stations: [{name: ' ', ae_title: CT01}]\n", "name"),
        ("      stations: [{name: 'CT1号機 ', ae_title: CT01}]\n", "leading or trailing spaces"),
        ("      stations: [{name: MR1号機, ae_title: CT01}]\n", "station names must be unique: MR1号機"),
        ("      stations: []\n", "stations"),
    ],
)
def test_station_registry_errors(tmp_path: Path, ct: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=re.escape(message)):
        load_config(_config_with_ct(tmp_path, ct))


@pytest.mark.parametrize(
    "ct",
    [
        "      station_ae_titles: [CT01]\n      stations: [{name: CT1号機, ae_title: CT01}]\n",
        "      station_name: CT01\n      stations: [{name: CT1号機, ae_title: CT01}]\n",
    ],
)
def test_old_station_keys_are_rejected(tmp_path: Path, ct: str) -> None:
    with pytest.raises(ConfigurationError, match="no longer supported; write stations"):
        load_config(_config_with_ct(tmp_path, ct))


def test_roster_errors(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("patients: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="non-empty"):
        load_roster(empty)
    bad = tmp_path / "bad.yaml"
    bad.write_text("patients:\n  - patient_id: P1\n    patient_name: {}\n    sex: X\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="#1"):
        load_roster(bad)
