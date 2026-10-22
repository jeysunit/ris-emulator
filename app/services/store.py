"""予約の保存（SQLite。ADR-0002）.

画面・CLI・MWL の SCP が別のスレッドやプロセスから同じファイルを使うので、
操作のたびに接続を開いて閉じる。予約の中身は JSON の列に入れ、
絞り込みに使う値だけを列に持つ。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.core.exceptions import InvalidTransitionError, OrderNotFoundError
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
"""


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


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
