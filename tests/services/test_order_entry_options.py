"""予約作成で選ぶ検査の種類・名簿の患者と、予約枠の刻みの設定（openspec/changes/rework-order-entry）."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.exceptions import ConfigurationError, ValidationError
from app.services.config import load_config
from app.services.order_service import OrderRequest, OrderService
from tests.conftest import ROOT, TODAY


def test_chosen_procedure_and_roster_patient(service: OrderService) -> None:
    order = service.create_orders(
        OrderRequest(
            counts={"MR": 1},
            scheduled_date=TODAY,
            procedure_code="MR0002",
            patient_source="roster",
            roster_patient_id="P000002",
        )
    )[0]
    assert order.procedure.code == "MR0002" and order.procedure.name == "腰椎 MRI 単純"
    assert order.patient.patient_id == "P000002"
    assert order.patient.name.ideographic == "佐藤^由紀"


def test_unknown_procedure_and_patient_are_rejected(service: OrderService) -> None:
    with pytest.raises(ValidationError, match="MR の検査の種類に無いコードです: CT0001"):
        service.create_orders(
            OrderRequest(counts={"MR": 1}, scheduled_date=TODAY, procedure_code="CT0001")
        )
    with pytest.raises(ValidationError, match="名簿に無い患者ID です: P999999"):
        service.create_orders(
            OrderRequest(
                counts={"CT": 1},
                scheduled_date=TODAY,
                patient_source="roster",
                roster_patient_id="P999999",
            )
        )
    assert service.list_orders() == []


def test_slot_minutes(tmp_path: Path) -> None:
    raw = yaml.safe_load((ROOT / "config" / "app_config.yaml").read_text(encoding="utf-8"))
    assert load_config(ROOT / "config" / "app_config.yaml").orders.slot_minutes == 15
    for value in (1, 5, 10, 15, 20, 30, 60):
        raw["orders"]["slot_minutes"] = value
        path = tmp_path / f"ok{value}.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        assert load_config(path).orders.slot_minutes == value
    for value in (0, 7, 45, 90):
        raw["orders"]["slot_minutes"] = value
        path = tmp_path / f"ng{value}.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_config(path)
