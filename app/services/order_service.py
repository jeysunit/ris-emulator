"""予約を作る・一覧する・状態を変える（docs/spec/01_orders.md）."""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

import pydantic
from pydantic import BaseModel, Field, field_validator

from app.core.charset import find_unencodable
from app.core.exceptions import ConfigurationError, ValidationError
from app.core.models import (
    CHARACTER_SET_TERMS,
    LO_MAX_LENGTH,
    CharacterSet,
    Order,
    OrderStatus,
    Patient,
    has_control_chars,
    validate_ae_title,
)
from app.core.mwl_dataset import order_to_dataset
from app.core.patient_factory import make_patient, make_patient_id, make_person_name

from .config import AppConfig
from .roster import load_roster
from .store import OrderStore

MAX_ORDERS_PER_REQUEST = 200
MAX_INTERVAL_MINUTES = 24 * 60
DAILY_SEQUENCE_MAX = 9999
PATIENT_ID_ATTEMPTS = 20
UID_ROOT = "2.25"
MIN_YEAR = 1900
MAX_YEAR = 9999
PatientSource = Literal["random", "roster"]


def check_scheduled_date(value: date) -> date:
    """予定の日は 1900〜9999 年（予定の日の前後を数えるときにあふれない範囲）."""
    if not MIN_YEAR <= value.year <= MAX_YEAR:
        raise ValidationError(f"予定日は {MIN_YEAR}〜{MAX_YEAR} 年にしてください")
    return value


class OrderRequest(BaseModel):
    """予約の作り方。`counts` はモダリティごとの件数（例 {"CT": 3, "MR": 1}）."""

    model_config = {"frozen": True}

    counts: dict[str, int] = Field(..., min_length=1)
    scheduled_date: date
    start_time: time = time(9, 0)
    interval_minutes: int = Field(15, ge=0, le=MAX_INTERVAL_MINUTES)
    patient_source: PatientSource = "random"
    character_set: CharacterSet | None = None
    station_ae_title: str | None = None
    department: str | None = None
    seed: int | None = None

    @field_validator("scheduled_date")
    @classmethod
    def _check_date(cls, value: date) -> date:
        if not MIN_YEAR <= value.year <= MAX_YEAR:
            raise ValueError(f"scheduled_date must be in {MIN_YEAR}-{MAX_YEAR}")
        return value


def parse_count_spec(text: str) -> tuple[str, int]:
    """`CT=3`・`CT:3`・`CT`（1 件）を (モダリティ, 件数) にする."""
    for separator in ("=", ":"):
        if separator in text:
            modality, _, count_text = text.partition(separator)
            break
    else:
        modality, count_text = text, "1"
    modality = modality.strip().upper()
    try:
        count = int(count_text)
    except ValueError as exc:
        raise ValidationError(f"件数が数ではありません: {text}") from exc
    if not modality or count < 1:
        raise ValidationError(f"モダリティと 1 以上の件数を指定してください: {text}")
    return modality, count


def parse_date_option(text: str, today: date) -> date:
    """`today`・`tomorrow`・`YYYYMMDD`・`YYYY-MM-DD` を日付にする（1900〜9999 年）."""
    if text in ("", "today"):
        return today
    if text == "tomorrow":
        try:
            return check_scheduled_date(today + timedelta(days=1))
        except OverflowError as exc:
            raise ValidationError(f"予定日は {MIN_YEAR}〜{MAX_YEAR} 年にしてください") from exc
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        return check_scheduled_date(parsed)
    raise ValidationError(f"日付は today・tomorrow・YYYYMMDD のどれかで指定してください: {text}")


def parse_time_option(text: str) -> time:
    """`HH:MM`・`HHMM` を時刻にする."""
    for pattern in ("%H:%M", "%H%M"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    raise ValidationError(f"時刻は HH:MM で指定してください: {text}")


def _check_lo_text(label: str, value: str) -> None:
    """LO の値（64 字まで、`\\` と制御文字なし）か確かめる."""
    if len(value) > LO_MAX_LENGTH:
        raise ValidationError(f"{label}は {LO_MAX_LENGTH} 字までにしてください")
    if "\\" in value or has_control_chars(value):
        raise ValidationError(f"{label}に「\\」と制御文字は使えません")


def check_encodable(order: Order) -> None:
    """予約の文字の値が、選んだ Specific Character Set で書けるかを確かめる.

    pydicom は書けない字を黙って `?` に置き換えるので、保存の前に止める。
    """
    problems = find_unencodable(order_to_dataset(order))
    if problems:
        attribute, chars = problems[0]
        label = "\\".join(CHARACTER_SET_TERMS[order.character_set])
        raise ValidationError(
            f"{attribute} の「{chars}」は {label} で書けません。文字コードを ISO_IR 192 にするか、"
            f"値を直してください（患者 ID {order.patient.patient_id}）"
        )


class OrderService:
    def __init__(
        self,
        config: AppConfig,
        store: OrderStore | None = None,
        today: Callable[[], date] = date.today,
    ):
        self.config = config
        self.store = store or OrderStore(Path(config.database))
        self.today = today

    def create_orders(self, request: OrderRequest) -> list[Order]:
        """予約を作って保存する。どこかで誤りがあれば何も保存せず、連番も使わない."""
        catalog = self.config.orders.modalities
        total = sum(request.counts.values())
        if total > MAX_ORDERS_PER_REQUEST:
            raise ValidationError(f"一度に作れる予約は {MAX_ORDERS_PER_REQUEST} 件までです（{total} 件）")
        unknown = [modality for modality in request.counts if modality not in catalog]
        if unknown:
            known = ", ".join(catalog)
            raise ValidationError(f"設定に無いモダリティです: {', '.join(unknown)}（設定: {known}）")
        if request.station_ae_title is not None:
            try:
                validate_ae_title(request.station_ae_title)
            except ValueError as exc:
                raise ValidationError(f"AE タイトルが正しくありません: {exc}") from exc
        if request.department is not None:
            _check_lo_text("依頼科", request.department)
        check_scheduled_date(request.scheduled_date)
        for modality, count in request.counts.items():
            if count < 1:
                raise ValidationError(f"件数は 1 以上にしてください: {modality}={count}")
            self._check_schedule_fits(request, count)

        roster = self._load_roster() if request.patient_source == "roster" else []
        created = self.today()

        def build(numbers: list[int], patient_id_exists: Callable[[str], bool]) -> list[Order]:
            if numbers[-1] > DAILY_SEQUENCE_MAX:
                raise ValidationError(f"1 日に作れる予約は {DAILY_SEQUENCE_MAX} 件までです")
            orders = self._build_orders(request, roster, created, numbers, patient_id_exists)
            for order in orders:
                check_encodable(order)
            return orders

        return self.store.add_numbered_orders(f"accession:{created:%Y%m%d}", total, build)

    def _build_orders(
        self,
        request: OrderRequest,
        roster: list[Patient],
        created: date,
        numbers: list[int],
        patient_id_exists: Callable[[str], bool],
    ) -> list[Order]:
        catalog = self.config.orders.modalities
        rng = random.Random(request.seed)
        prefix = self.config.orders.accession_prefix
        stamp = created.strftime("%Y%m%d")
        character_set = request.character_set or self.config.orders.default_character_set
        orders: list[Order] = []
        used_ids: set[str] = set()
        index = 0
        for modality, count in request.counts.items():
            entry = catalog[modality]
            for slot in range(count):
                number = f"{stamp}{numbers[index]:04d}"
                index += 1
                start = datetime.combine(request.scheduled_date, request.start_time) + timedelta(
                    minutes=request.interval_minutes * slot
                )
                physician = make_person_name(rng, rng.choice(("M", "F")))
                patient = self._patient(
                    rng, roster, request.scheduled_date, used_ids, patient_id_exists
                )
                try:
                    order = Order(
                        accession_number=f"{prefix}{number}",
                        requested_procedure_id=f"RP{number}",
                        scheduled_procedure_step_id=f"SPS{number}",
                        study_instance_uid=f"{UID_ROOT}.{uuid.uuid4().int}",
                        issuer_namespace=self.config.orders.issuer_namespace,
                        patient=patient,
                        modality=modality,
                        scheduled_station_ae_title=request.station_ae_title
                        or entry.station_ae_titles[slot % len(entry.station_ae_titles)],
                        scheduled_station_name=entry.station_name,
                        scheduled_date=start.strftime("%Y%m%d"),
                        scheduled_time=start.strftime("%H%M%S"),
                        procedure=rng.choice(entry.procedures),
                        requesting_service=request.department
                        or rng.choice(self.config.orders.departments),
                        requesting_physician=physician,
                        referring_physician=physician,
                        institution_name=self.config.orders.institution_name,
                        character_set=character_set,
                    )
                except pydantic.ValidationError as exc:
                    first = exc.errors()[0]
                    location = ".".join(str(part) for part in first["loc"])
                    raise ValidationError(f"予約の値が正しくありません: {location}: {first['msg']}") from exc
                orders.append(order)
        return orders

    def list_orders(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
        statuses: list[OrderStatus] | None = None,
        modality: str = "",
    ) -> list[Order]:
        return self.store.list_orders(
            date_from=date_from, date_to=date_to, statuses=statuses, modality=modality
        )

    def get(self, accession_number: str) -> Order:
        return self.store.get(accession_number)

    def set_status(self, accession_number: str, status: OrderStatus) -> Order:
        return self.store.set_status(accession_number, status)

    def _check_schedule_fits(self, request: OrderRequest, count: int) -> None:
        start = datetime.combine(request.scheduled_date, request.start_time)
        try:
            last = start + timedelta(minutes=request.interval_minutes * (count - 1))
        except OverflowError:
            last = None  # 9999-12-31 を越える
        if last is None or last.date() != request.scheduled_date:
            raise ValidationError(
                "予定の時刻がその日のうちに収まりません。開始の時刻か間隔を見直してください"
            )

    def _load_roster(self) -> list[Patient]:
        path = Path(self.config.orders.roster_path)
        roster = load_roster(path)
        if not roster:
            raise ConfigurationError("Roster is empty", {"path": str(path)})
        return roster

    def _patient(
        self,
        rng: random.Random,
        roster: list[Patient],
        reference: date,
        used: set[str],
        patient_id_exists: Callable[[str], bool],
    ) -> Patient:
        """名簿があれば名簿から選ぶ。無ければ、まだ使っていない患者 ID で乱数の患者を作る."""
        if roster:
            return rng.choice(roster)
        prefix = self.config.orders.patient_id_prefix
        for _ in range(PATIENT_ID_ATTEMPTS):
            patient_id = make_patient_id(rng, prefix)
            if patient_id not in used and not patient_id_exists(patient_id):
                used.add(patient_id)
                return make_patient(rng, patient_id=patient_id, reference_date=reference)
        raise ValidationError("空いている患者 ID が見つかりません。patient_id_prefix を変えてください")
