"""撮り直しの予約の試験（docs/spec/01_orders.md 7 章）."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from app.core.exceptions import (
    ConfigurationError,
    InvalidTransitionError,
    OrderNotFoundError,
    ValidationError,
)
from app.core.models import Order, OrderStatus
from app.services.config import AppConfig, load_config
from app.services.order_service import OrderRequest, OrderService
from app.services.store import OrderStore

from tests.conftest import ROOT, TODAY, new_order_service


@pytest.fixture
def retaking(config: AppConfig, store: OrderStore) -> OrderService:
    return new_order_service(config, store)


def _order(service: OrderService, status: OrderStatus | None = None) -> Order:
    order = service.create_orders(OrderRequest(counts={"CT": 1}, scheduled_date=TODAY, seed=1))[0]
    if status in (OrderStatus.COMPLETED, OrderStatus.DISCONTINUED):
        service.set_status(order.accession_number, OrderStatus.IN_PROGRESS)
    if status is not None:
        service.set_status(order.accession_number, status)
    return service.get(order.accession_number)


def test_default_mode_is_append(config: AppConfig) -> None:
    assert config.orders.retake_mode == "append"


def test_unknown_mode_is_rejected(tmp_path: Path) -> None:
    raw = (ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8")
    path = tmp_path / "app_config.yaml"
    changed = raw.replace('retake_mode: "append"', 'retake_mode: "copy"')
    assert changed != raw
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_config(path)
    assert "append" in str(error.value) and "new_order" in str(error.value)


def test_append_mode_does_not_create(service: OrderService) -> None:
    order = _order(service, OrderStatus.COMPLETED)
    with pytest.raises(ValidationError, match="append"):
        service.create_retake(order.accession_number)
    assert len(service.list_orders()) == 1


def test_identifiers_are_all_new(retaking: OrderService) -> None:
    original = _order(retaking, OrderStatus.COMPLETED)
    retake, after = retaking.create_retake(original.accession_number)
    assert retake.accession_number == "RE202610210002"
    for field in (
        "accession_number",
        "requested_procedure_id",
        "scheduled_procedure_step_id",
        "study_instance_uid",
    ):
        assert getattr(retake, field) != getattr(original, field)
    assert retake.patient == original.patient
    assert retake.procedure == original.procedure
    assert retake.modality == original.modality
    assert retake.scheduled_station_ae_title == original.scheduled_station_ae_title
    assert retake.requesting_physician == original.requesting_physician
    assert retake.character_set == original.character_set
    assert retake.status is OrderStatus.SCHEDULED
    assert retake.retake_of == original.accession_number
    # 予定日時の既定は作った時点（分まで）
    assert (retake.scheduled_date, retake.scheduled_time) == ("20261021", "143700")
    assert after.status is OrderStatus.COMPLETED
    assert retaking.list_retakes(original.accession_number) == [retaking.get(retake.accession_number)]


def test_date_and_time_can_be_given(retaking: OrderService) -> None:
    original = _order(retaking, OrderStatus.COMPLETED)
    retake, _ = retaking.create_retake(
        original.accession_number, scheduled_date=date(2026, 10, 22), start_time=time(9, 30)
    )
    assert (retake.scheduled_date, retake.scheduled_time) == ("20261022", "093000")


def test_in_progress_original_becomes_discontinued(retaking: OrderService) -> None:
    original = _order(retaking, OrderStatus.IN_PROGRESS)
    _, after = retaking.create_retake(original.accession_number)
    assert after.status is OrderStatus.DISCONTINUED
    assert retaking.get(original.accession_number).status is OrderStatus.DISCONTINUED


@pytest.mark.parametrize("status", [OrderStatus.COMPLETED, OrderStatus.DISCONTINUED])
def test_final_original_stays(retaking: OrderService, status: OrderStatus) -> None:
    original = _order(retaking, status)
    _, after = retaking.create_retake(original.accession_number)
    assert after.status is status
    assert retaking.get(original.accession_number).updated_at == original.updated_at


@pytest.mark.parametrize("status", [None, OrderStatus.CANCELLED])
def test_scheduled_and_cancelled_cannot_retake(
    retaking: OrderService, status: OrderStatus | None
) -> None:
    original = _order(retaking, status)
    with pytest.raises(InvalidTransitionError, match="撮り直しを作れません"):
        retaking.create_retake(original.accession_number)
    assert len(retaking.list_orders()) == 1


def test_unknown_original(retaking: OrderService) -> None:
    with pytest.raises(OrderNotFoundError):
        retaking.create_retake("NOPE")


def test_failure_leaves_nothing(retaking: OrderService, monkeypatch: pytest.MonkeyPatch) -> None:
    """途中で失敗したら、撮り直しの予約も元の予約の変更も残らず、連番も使わない."""
    original = _order(retaking, OrderStatus.IN_PROGRESS)

    def fail(order: Order) -> None:
        raise ValidationError("書けない字があります")

    monkeypatch.setattr("app.services.order_service.check_encodable", fail)
    with pytest.raises(ValidationError):
        retaking.create_retake(original.accession_number)
    monkeypatch.undo()
    assert retaking.get(original.accession_number).status is OrderStatus.IN_PROGRESS
    assert len(retaking.list_orders()) == 1
    retake, _ = retaking.create_retake(original.accession_number)
    assert retake.accession_number == "RE202610210002"


def test_retake_of_a_retake(retaking: OrderService) -> None:
    original = _order(retaking, OrderStatus.COMPLETED)
    first, _ = retaking.create_retake(original.accession_number)
    retaking.set_status(first.accession_number, OrderStatus.IN_PROGRESS)
    second, after = retaking.create_retake(first.accession_number)
    assert second.retake_of == first.accession_number
    assert after.status is OrderStatus.DISCONTINUED
