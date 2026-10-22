"""試験の共通の部品."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from app.services.config import AppConfig, load_config
from app.services.order_service import OrderService
from app.services.store import OrderStore

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 14, 37, 52)


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    """リポジトリの設定の例を、保存先と名簿だけ試験用に変えたもの."""
    base = load_config(ROOT / "config" / "app_config.yaml")
    orders = base.orders.model_copy(
        update={"roster_path": str(ROOT / "data" / "patients_sample.yaml")}
    )
    mwl = base.mwl.model_copy(update={"port": 0})
    return base.model_copy(
        update={"database": str(tmp_path / "ris.sqlite3"), "orders": orders, "mwl": mwl}
    )


@pytest.fixture
def store(config: AppConfig) -> OrderStore:
    return OrderStore(Path(config.database))


@pytest.fixture
def service(config: AppConfig, store: OrderStore) -> OrderService:
    return OrderService(config, store, today=lambda: TODAY)


def new_order_service(config: AppConfig, store: OrderStore) -> OrderService:
    """撮り直しの扱いを new_order にした OrderService（今の時刻は NOW に固定）."""
    orders = config.orders.model_copy(update={"retake_mode": "new_order"})
    return OrderService(
        config.model_copy(update={"orders": orders}), store, today=lambda: TODAY, now=lambda: NOW
    )
