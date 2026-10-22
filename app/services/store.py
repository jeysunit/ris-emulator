"""予約の保存（SQLite。ADR-0002）.

画面・CLI・MWL の SCP が別のスレッドやプロセスから同じファイルを使うので、
操作のたびに接続を開いて閉じる。予約の中身は JSON の列に入れ、
絞り込みに使う値だけを列に持つ。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.exceptions import (
    DuplicateMppsError,
    InvalidTransitionError,
    MppsNotFoundError,
    MppsNotInProgressError,
    OrderNotFoundError,
)
from app.core.models import STATUS_LABELS, Order, OrderStatus, can_transition

BUSY_TIMEOUT_SECONDS = 10.0
# (連番, 患者 ID の有無を引く関数) → 保存する予約
OrderBuilder = Callable[[list[int], Callable[[str], bool]], list[Order]]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accession_number TEXT NOT NULL UNIQUE,
    patient_id TEXT NOT NULL,
    modality TEXT NOT NULL,
    scheduled_station_ae_title TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    status TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_schedule ON orders (scheduled_date, scheduled_time);
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mpps (
    sop_instance_uid TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    accession_numbers TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
# MPPS の Performed Procedure Step Status (0040,0252) の Enumerated Values（PS3.3 C.4.14）
PPS_IN_PROGRESS = "IN PROGRESS"
PPS_COMPLETED = "COMPLETED"
PPS_DISCONTINUED = "DISCONTINUED"
PPS_STATUSES = frozenset({PPS_IN_PROGRESS, PPS_COMPLETED, PPS_DISCONTINUED})
# MPPS の状態 → 結び付いた予約の状態
_ORDER_STATUS_FOR_PPS = {
    PPS_IN_PROGRESS: OrderStatus.IN_PROGRESS,
    PPS_COMPLETED: OrderStatus.COMPLETED,
    PPS_DISCONTINUED: OrderStatus.DISCONTINUED,
}


@dataclass(frozen=True)
class MppsRecord:
    """受け付けた MPPS の1件（docs/spec/05_mpps_scp.md 4 章）."""

    sop_instance_uid: str
    status: str
    accession_numbers: list[str]
    body: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MppsResult:
    """MPPS の処理の結果。`unchanged` は遷移の表に無いので状態を変えなかった予約."""

    linked: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[tuple[str, OrderStatus]] = field(default_factory=list)


class OrderStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
        finally:
            conn.close()

    def add_numbered_orders(self, counter: str, count: int, build: OrderBuilder) -> list[Order]:
        """連番を `count` 個取り、`build` で作った予約をまとめて足す.

        連番の取得・予約の組み立て・保存を1つのトランザクションで行う。`build` が
        例外を出せば何も残さない（連番に欠番を作らない）。`build` には連番と、
        同じトランザクションで患者 ID の有無を引く関数を渡す。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT value FROM counters WHERE name = ?", (counter,)
                ).fetchone()
                start = (row[0] if row else 0) + 1
                numbers = list(range(start, start + count))

                def patient_id_exists(patient_id: str) -> bool:
                    found = conn.execute(
                        "SELECT 1 FROM orders WHERE patient_id = ? LIMIT 1", (patient_id,)
                    ).fetchone()
                    return found is not None

                now = _now()
                saved = [
                    order.model_copy(update={"created_at": now, "updated_at": now})
                    for order in build(numbers, patient_id_exists)
                ]
                conn.execute(
                    "INSERT INTO counters (name, value) VALUES (?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                    (counter, numbers[-1]),
                )
                for order in saved:
                    conn.execute(
                        "INSERT INTO orders (accession_number, patient_id, modality, "
                        "scheduled_station_ae_title, scheduled_date, scheduled_time, status, body) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            order.accession_number,
                            order.patient.patient_id,
                            order.modality,
                            order.scheduled_station_ae_title,
                            order.scheduled_date,
                            order.scheduled_time,
                            order.status.value,
                            order.model_dump_json(),
                        ),
                    )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return saved

    def get(self, accession_number: str) -> Order:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT body FROM orders WHERE accession_number = ?", (accession_number,)
            ).fetchone()
        if row is None:
            raise OrderNotFoundError("Order not found", {"accession_number": accession_number})
        return Order.model_validate_json(row[0])

    def list_orders(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
        statuses: list[OrderStatus] | None = None,
        modality: str = "",
    ) -> list[Order]:
        """予約を予定の日時の順に返す。空の条件は絞らない."""
        clauses: list[str] = []
        params: list[str] = []
        if date_from:
            clauses.append("scheduled_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("scheduled_date <= ?")
            params.append(date_to)
        if statuses:
            clauses.append(f"status IN ({', '.join('?' for _ in statuses)})")
            params.extend(status.value for status in statuses)
        if modality:
            clauses.append("modality = ?")
            params.append(modality)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT body FROM orders {where} "  # noqa: S608 - 列名と ? だけを組む
                "ORDER BY scheduled_date, scheduled_time, id",
                params,
            ).fetchall()
        return [Order.model_validate_json(row[0]) for row in rows]

    def set_status(self, accession_number: str, status: OrderStatus) -> Order:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT body FROM orders WHERE accession_number = ?", (accession_number,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise OrderNotFoundError(
                    "Order not found", {"accession_number": accession_number}
                )
            current = Order.model_validate_json(row[0])
            if status == current.status:
                # 同じ状態は何もしない（更新日時も変えない）
                conn.execute("ROLLBACK")
                return current
            if not can_transition(current.status, status):
                conn.execute("ROLLBACK")
                raise InvalidTransitionError(
                    f"{STATUS_LABELS[current.status]}の予約は"
                    f"{STATUS_LABELS[status]}に変更できません",
                    {"accession_number": accession_number, "status": current.status.value},
                )
            order = current.model_copy(update={"status": status, "updated_at": _now()})
            conn.execute(
                "UPDATE orders SET status = ?, body = ? WHERE accession_number = ?",
                (status.value, order.model_dump_json(), accession_number),
            )
            conn.execute("COMMIT")
        return order


    def create_mpps(
        self,
        sop_instance_uid: str,
        steps: Sequence[tuple[str, str]],
        body: dict[str, Any],
    ) -> MppsResult:
        """N-CREATE（IN PROGRESS）の MPPS を記録し、結び付いた予約を実施中にする.

        `steps` は Scheduled Step Attributes Sequence の項目の
        (Accession Number, Scheduled Procedure Step ID)。両方が一致する予約に結び付ける。
        MPPS の記録と予約の状態の変更は1つのトランザクションで行う。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                found = conn.execute(
                    "SELECT 1 FROM mpps WHERE sop_instance_uid = ?", (sop_instance_uid,)
                ).fetchone()
                if found is not None:
                    raise DuplicateMppsError(
                        "MPPS already exists", {"sop_instance_uid": sop_instance_uid}
                    )
                orders = _orders_for_steps(conn, steps)
                result = _apply_mpps(conn, orders, OrderStatus.IN_PROGRESS)
                now = _now()
                conn.execute(
                    "INSERT INTO mpps (sop_instance_uid, status, accession_numbers, body, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        sop_instance_uid,
                        PPS_IN_PROGRESS,
                        json.dumps(result.linked),
                        json.dumps(body, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return result

    def update_mpps(
        self, sop_instance_uid: str, status: str | None, modifications: dict[str, Any]
    ) -> MppsResult:
        """N-SET の値を記録し、COMPLETED・DISCONTINUED なら結び付いた予約を完了・中止にする.

        記録した MPPS が無ければ MppsNotFoundError、IN PROGRESS でなければ
        MppsNotInProgressError（PS3.4 F.7.2.2.3）。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT status, accession_numbers, body FROM mpps WHERE sop_instance_uid = ?",
                    (sop_instance_uid,),
                ).fetchone()
                if row is None:
                    raise MppsNotFoundError(
                        "MPPS not found", {"sop_instance_uid": sop_instance_uid}
                    )
                if row[0] != PPS_IN_PROGRESS:
                    raise MppsNotInProgressError(
                        "MPPS may no longer be updated",
                        {"sop_instance_uid": sop_instance_uid, "status": row[0]},
                    )
                accession_numbers: list[str] = json.loads(row[1])
                new_status = status or row[0]
                result = MppsResult(linked=accession_numbers)
                if new_status != PPS_IN_PROGRESS:
                    orders = [_load_order(conn, number) for number in accession_numbers]
                    result = _apply_mpps(
                        conn,
                        [order for order in orders if order is not None],
                        _ORDER_STATUS_FOR_PPS[new_status],
                    )
                body = {**json.loads(row[2]), **modifications}
                conn.execute(
                    "UPDATE mpps SET status = ?, body = ?, updated_at = ? "
                    "WHERE sop_instance_uid = ?",
                    (new_status, json.dumps(body, ensure_ascii=False), _now(), sop_instance_uid),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return result

    def list_mpps(self, accession_number: str) -> list[MppsRecord]:
        """予約に結び付いた MPPS を、受けた順に返す."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sop_instance_uid, status, accession_numbers, body, created_at, updated_at "
                "FROM mpps WHERE EXISTS "
                "(SELECT 1 FROM json_each(mpps.accession_numbers) WHERE value = ?) "
                "ORDER BY created_at, rowid",
                (accession_number,),
            ).fetchall()
        return [
            MppsRecord(
                sop_instance_uid=row[0],
                status=row[1],
                accession_numbers=json.loads(row[2]),
                body=json.loads(row[3]),
                created_at=row[4],
                updated_at=row[5],
            )
            for row in rows
        ]


def _load_order(conn: sqlite3.Connection, accession_number: str) -> Order | None:
    row = conn.execute(
        "SELECT body FROM orders WHERE accession_number = ?", (accession_number,)
    ).fetchone()
    return Order.model_validate_json(row[0]) if row else None


def _orders_for_steps(
    conn: sqlite3.Connection, steps: Sequence[tuple[str, str]]
) -> list[Order]:
    """Accession Number と Scheduled Procedure Step ID の両方が一致する予約（重ねない）."""
    orders: list[Order] = []
    for accession_number, step_id in steps:
        if not accession_number or not step_id:
            continue
        order = _load_order(conn, accession_number)
        if order is None or order.scheduled_procedure_step_id != step_id:
            continue
        if all(o.accession_number != order.accession_number for o in orders):
            orders.append(order)
    return orders


def _apply_mpps(
    conn: sqlite3.Connection, orders: list[Order], status: OrderStatus
) -> MppsResult:
    """MPPS が求める状態へ予約を変える。遷移の表に無ければ変えずに `unchanged` に入れる."""
    result = MppsResult(linked=[order.accession_number for order in orders])
    now = _now()
    for order in orders:
        if order.status == status:
            continue
        if not can_transition(order.status, status):
            result.unchanged.append((order.accession_number, order.status))
            continue
        updated = order.model_copy(update={"status": status, "updated_at": now})
        conn.execute(
            "UPDATE orders SET status = ?, body = ? WHERE accession_number = ?",
            (status.value, updated.model_dump_json(), order.accession_number),
        )
        result.changed.append(order.accession_number)
    return result


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
