"""試験の共通の部品."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid

from app.mwl.mpps import STATUS_SUCCESS, handle_n_create
from app.services.config import AppConfig, load_config
from app.services.order_service import OrderService
from app.services.store import OrderStore

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 14, 37, 52)
# 画面と CLI に出す版。git の状態に左右されないよう、試験では環境変数で固定する（app/version.py）
TEST_VERSION = "0.2.0+37.g60970f9"


@pytest.fixture(autouse=True)
def fixed_app_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_VERSION", TEST_VERSION)


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


def add_unscheduled_mpps(
    store: OrderStore,
    *,
    patient_id: str = "ER2026102400",
    name: str = "UNKNOWN^MALE=不明^男性=フメイ^ダンセイ",
    birth_date: str = "",
    sex: str = "M",
    modality: str = "CT",
    station_ae_title: str = "DTG_CT01",
    study_instance_uid: str | None = None,
    status: str = "IN PROGRESS",
) -> tuple[str, str]:
    """予約の無い撮影（緊急）の MPPS を N-CREATE の処理で記録する。(SOP Instance UID, Study Instance UID)."""
    sop_instance_uid = generate_uid()
    study_uid = study_instance_uid or generate_uid()
    step = Dataset()
    step.StudyInstanceUID = study_uid
    step.AccessionNumber = ""
    step.ScheduledProcedureStepID = ""
    attributes = Dataset()
    attributes.SpecificCharacterSet = "ISO_IR 192"
    attributes.ScheduledStepAttributesSequence = [step]
    attributes.PatientName = name
    attributes.PatientID = patient_id
    attributes.PatientBirthDate = birth_date
    attributes.PatientSex = sex
    attributes.PerformedProcedureStepID = "PPS1"
    attributes.PerformedStationAETitle = station_ae_title
    attributes.PerformedStationName = "CT01"
    attributes.PerformedProcedureStepStartDate = "20261021"
    attributes.PerformedProcedureStepStartTime = "101530.123"
    attributes.PerformedProcedureStepStatus = "IN PROGRESS"
    attributes.Modality = modality
    status_code, _ = handle_n_create(store, sop_instance_uid, attributes)
    assert status_code == STATUS_SUCCESS
    if status != "IN PROGRESS":
        store.update_mpps(sop_instance_uid, status, {"PerformedProcedureStepStatus": {"vr": "CS", "Value": [status]}})
    return sop_instance_uid, study_uid


def new_order_service(config: AppConfig, store: OrderStore) -> OrderService:
    """撮り直しの扱いを new_order にした OrderService（今の時刻は NOW に固定）."""
    orders = config.orders.model_copy(update={"retake_mode": "new_order"})
    return OrderService(
        config.model_copy(update={"orders": orders}), store, today=lambda: TODAY, now=lambda: NOW
    )
