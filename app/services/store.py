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
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.exceptions import (
    AlreadyReconciledError,
    DuplicateMppsError,
    InvalidTransitionError,
    MppsNotFoundError,
    MppsNotInProgressError,
    OrderNotFoundError,
    ReconciliationNotFoundError,
)
from app.core.models import STATUS_LABELS, Order, OrderStatus, can_transition

BUSY_TIMEOUT_SECONDS = 10.0
# (連番, 患者ID の有無を引く関数) → 保存する予約
OrderBuilder = Callable[[list[int], Callable[[str], bool]], list[Order]]
# (連番, 元の予約) → 撮り直しの予約
RetakeBuilder = Callable[[int, Order], Order]

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
CREATE TABLE IF NOT EXISTS reconciliations (
    accession_number TEXT PRIMARY KEY,
    sop_instance_uid TEXT NOT NULL UNIQUE,
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


@dataclass(frozen=True)
class Delivery:
    """照合で送る HL7 の1通（docs/spec/07_reconciliation.md 4 章）.

    `outcome` は pending（未送信）・accepted・rejected・failed。`text` は組み立てた本文で、
    送り直すときは同じ本文（同じ MSH-10）を送る。
    """

    kind: str
    message_type: str
    control_id: str = ""
    text: str = ""
    outcome: str = "pending"
    ack_code: str = ""
    detail: str = ""
    attempts: int = 0
    sent_at: str = ""
    # 送信の途中（他のプロセスが同じ通を同時に送らないための印。UNIX 秒。空なら途中ではない）
    claimed_at: float = 0.0


@dataclass(frozen=True)
class Reconciliation:
    """照合の記録。仮の患者の値と、HL7 の送信の経過."""

    accession_number: str
    sop_instance_uid: str
    temporary: dict[str, str]
    deliveries: list[Delivery]
    created_at: str
    updated_at: str


# 予約と送る HL7 の組み立て：(連番, MPPS の記録) → (予約, 送る HL7, 仮の患者の値)。
# 同じトランザクションで読んだ MPPS から作る。予約の状態は store が MPPS に合わせて決める
ReconcileBuilder = Callable[[int, MppsRecord], tuple[Order, list[Delivery], dict[str, str]]]


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
        同じトランザクションで患者ID の有無を引く関数を渡す。
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
                    _insert_order(conn, order)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return saved

    def add_retake_order(
        self,
        counter: str,
        accession_number: str,
        build: RetakeBuilder,
        retake_from: frozenset[OrderStatus],
    ) -> tuple[Order, Order]:
        """元の予約から撮り直しの予約を作って足し、元の予約の状態を合わせる.

        元の予約の状態の確認・連番の取得・撮り直しの予約の保存・元の予約の状態の変更を
        1つのトランザクションで行う（docs/spec/01_orders.md 7 章）。元の予約の状態が
        `retake_from` に無ければ InvalidTransitionError。元の予約が実施中なら中止にし、
        完了・中止ならそのままにする。戻り値は (撮り直しの予約, 元の予約)。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                original = _load_order(conn, accession_number)
                if original is None:
                    raise OrderNotFoundError(
                        "Order not found", {"accession_number": accession_number}
                    )
                if original.status not in retake_from:
                    raise InvalidTransitionError(
                        f"{STATUS_LABELS[original.status]}の予約からは撮り直しを作れません",
                        {"accession_number": accession_number, "status": original.status.value},
                    )
                row = conn.execute(
                    "SELECT value FROM counters WHERE name = ?", (counter,)
                ).fetchone()
                number = (row[0] if row else 0) + 1
                now = _now()
                retake = build(number, original).model_copy(
                    update={"created_at": now, "updated_at": now}
                )
                conn.execute(
                    "INSERT INTO counters (name, value) VALUES (?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                    (counter, number),
                )
                _insert_order(conn, retake)
                if original.status is OrderStatus.IN_PROGRESS:
                    # 始めた撮影は正常に終わらなかった（PS3.3 C.4.14 の DISCONTINUED）
                    original = original.model_copy(
                        update={"status": OrderStatus.DISCONTINUED, "updated_at": now}
                    )
                    conn.execute(
                        "UPDATE orders SET status = ?, body = ? WHERE accession_number = ?",
                        (original.status.value, original.model_dump_json(), accession_number),
                    )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return retake, original

    def list_retakes(self, accession_number: str) -> list[Order]:
        """その予約から作った撮り直しの予約（作った順）."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT body FROM orders WHERE json_extract(body, '$.retake_of') = ? ORDER BY id",
                (accession_number,),
            ).fetchall()
        return [Order.model_validate_json(row[0]) for row in rows]

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
        query: str = "",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Order]:
        """予約を予定の日時の順に返す。空の条件は絞らない。`limit` があれば `offset` 件目から切る."""
        where, params = _order_filter(date_from, date_to, statuses, modality, query)
        page = ""
        if limit is not None:
            page = " LIMIT ? OFFSET ?"
            params += [limit, offset]
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT body FROM orders {where} "  # noqa: S608 - 列名と ? だけを組む
                f"ORDER BY scheduled_date, scheduled_time, id{page}",
                params,
            ).fetchall()
        return [Order.model_validate_json(row[0]) for row in rows]

    def count_orders(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
        statuses: list[OrderStatus] | None = None,
        modality: str = "",
        query: str = "",
    ) -> int:
        """`list_orders` と同じ条件に合う予約の件数."""
        where, params = _order_filter(date_from, date_to, statuses, modality, query)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM orders {where}",  # noqa: S608 - 列名と ? だけを組む
                params,
            ).fetchone()
        return int(row[0])

    def count_orders_by_status(
        self, *, date_from: str = "", date_to: str = "", modality: str = "", query: str = ""
    ) -> dict[OrderStatus, int]:
        """状態の条件を外して、すべての状態の件数を返す."""
        where, params = _order_filter(date_from, date_to, None, modality, query)
        counts = dict.fromkeys(OrderStatus, 0)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT status, COUNT(*) FROM orders {where} GROUP BY status",  # noqa: S608
                params,
            ).fetchall()
        counts.update({OrderStatus(row[0]): int(row[1]) for row in rows})
        return counts

    def set_status(
        self, accession_number: str, status: OrderStatus,
        build_delivery: Callable[[Order], Delivery | None] | None = None,
    ) -> Order:
        """予約の状態を変える.

        照合で作った予約で、`build_delivery` が通を返せば、照合の記録の末尾に未送信で足す。
        状態の変更と通の追加は 1 つのトランザクションで行う（`build_delivery` が例外を出せば
        どちらも残さない）。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = _load_order(conn, accession_number)
                if current is None:
                    raise OrderNotFoundError("Order not found", {"accession_number": accession_number})
                if status == current.status:
                    # 同じ状態は何もしない（更新日時も変えず、通も足さない）
                    conn.execute("ROLLBACK")
                    return current
                if not can_transition(current.status, status):
                    raise InvalidTransitionError(
                        f"{STATUS_LABELS[current.status]}の予約は{STATUS_LABELS[status]}に変更できません",
                        {"accession_number": accession_number, "status": current.status.value},
                    )
                order = current.model_copy(update={"status": status, "updated_at": _now()})
                conn.execute(
                    "UPDATE orders SET status = ?, body = ? WHERE accession_number = ?",
                    (status.value, order.model_dump_json(), accession_number),
                )
                if build_delivery is not None:
                    row = conn.execute(
                        "SELECT body FROM reconciliations WHERE accession_number = ?",
                        (accession_number,),
                    ).fetchone()
                    if row is not None:
                        delivery = build_delivery(order)
                        if delivery is not None:
                            body = json.loads(row[0])
                            body["deliveries"].append(asdict(delivery))
                            conn.execute(
                                "UPDATE reconciliations SET body = ?, updated_at = ? WHERE accession_number = ?",
                                (json.dumps(body, ensure_ascii=False), _now(), accession_number),
                            )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return order

    def create_mpps(
        self,
        sop_instance_uid: str,
        steps: Sequence[tuple[str, str] | tuple[str, str, str]],
        body: dict[str, Any],
        patient_id: str = "",
    ) -> MppsResult:
        """N-CREATE（IN PROGRESS）の MPPS を記録し、結び付いた予約を実施中にする.

        `steps` は Scheduled Step Attributes Sequence の項目の
        (Accession Number, Scheduled Procedure Step ID, Study Instance UID)。
        受付番号が空なら、照合済みの予約を Study UID と患者ID で探す。
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
                orders = _orders_for_steps(conn, steps, patient_id)
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
        return [_mpps_record(row) for row in rows]

    def get_mpps(self, sop_instance_uid: str) -> MppsRecord:
        """SOP Instance UID の MPPS。無ければ MppsNotFoundError."""
        with self._connect() as conn:
            row = _select_mpps(conn, sop_instance_uid)
        if row is None:
            raise MppsNotFoundError("MPPS not found", {"sop_instance_uid": sop_instance_uid})
        return _mpps_record(row)

    def list_unlinked_mpps(self) -> list[MppsRecord]:
        """予約に結び付いていない MPPS を、受けた順に返す（照合の対象。docs/spec/07_reconciliation.md）."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sop_instance_uid, status, accession_numbers, body, created_at, updated_at "
                "FROM mpps WHERE json_array_length(accession_numbers) = 0 "
                "ORDER BY created_at, rowid"
            ).fetchall()
        return [_mpps_record(row) for row in rows]

    def reconcile_mpps(
        self,
        counter: str,
        sop_instance_uid: str,
        build: ReconcileBuilder,
    ) -> Order:
        """予約に結び付いていない MPPS に、新しい予約を結ぶ.

        連番の取得・予約の保存・MPPS と予約の結び付け・照合の記録を1つのトランザクションで行う。
        予約の状態は MPPS の状態に合わせる。MPPS が無ければ MppsNotFoundError、すでに予約に
        結び付いていれば AlreadyReconciledError で、何も変えない。`build` が例外を出せば何も
        残さない（連番に欠番を作らない）。`build` が返す HL7 は、照合の記録に未送信で残す。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = _select_mpps(conn, sop_instance_uid)
                if row is None:
                    raise MppsNotFoundError(
                        "MPPS not found", {"sop_instance_uid": sop_instance_uid}
                    )
                record = _mpps_record(row)
                if record.accession_numbers:
                    raise AlreadyReconciledError(
                        "この撮影はすでに予約に結び付いています",
                        {
                            "sop_instance_uid": sop_instance_uid,
                            "accession_number": record.accession_numbers[0],
                        },
                    )
                counter_row = conn.execute(
                    "SELECT value FROM counters WHERE name = ?", (counter,)
                ).fetchone()
                number = (counter_row[0] if counter_row else 0) + 1
                now = _now()
                built, deliveries, temporary = build(number, record)
                order = built.model_copy(
                    update={
                        "status": _ORDER_STATUS_FOR_PPS[record.status],
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                conn.execute(
                    "INSERT INTO counters (name, value) VALUES (?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                    (counter, number),
                )
                _insert_order(conn, order)
                conn.execute(
                    "UPDATE mpps SET accession_numbers = ? WHERE sop_instance_uid = ?",
                    (json.dumps([order.accession_number]), sop_instance_uid),
                )
                body = {
                    "temporary": temporary,
                    "deliveries": [asdict(delivery) for delivery in deliveries],
                }
                conn.execute(
                    "INSERT INTO reconciliations (accession_number, sop_instance_uid, body, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        order.accession_number,
                        sop_instance_uid,
                        json.dumps(body, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return order

    def get_reconciliation(self, accession_number: str) -> Reconciliation | None:
        """予約の照合の記録。照合で作った予約でなければ None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT accession_number, sop_instance_uid, body, created_at, updated_at "
                "FROM reconciliations WHERE accession_number = ?",
                (accession_number,),
            ).fetchone()
        if row is None:
            return None
        body = json.loads(row[2])
        return Reconciliation(
            accession_number=row[0],
            sop_instance_uid=row[1],
            temporary=body["temporary"],
            deliveries=[Delivery(**item) for item in body["deliveries"]],
            created_at=row[3],
            updated_at=row[4],
        )

    def claim_delivery(
        self, accession_number: str, index: int, now: float, lease_seconds: float
    ) -> Delivery | None:
        """`index` 番めの通を送る権利を取り、送った回数を 1 つ増やす.

        すでに受理されている、または他のプロセスが `lease_seconds` 以内に取っていれば None
        （同じ通を同時に送らない）。取った印は `update_delivery` で結果を書くときに外れる。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT body FROM reconciliations WHERE accession_number = ?",
                    (accession_number,),
                ).fetchone()
                if row is None:
                    raise ReconciliationNotFoundError(
                        "Reconciliation not found", {"accession_number": accession_number}
                    )
                body = json.loads(row[0])
                current = Delivery(**body["deliveries"][index])
                if current.outcome == "accepted" or now - current.claimed_at < lease_seconds:
                    conn.execute("ROLLBACK")
                    return None
                claimed = replace(current, attempts=current.attempts + 1, claimed_at=now)
                body["deliveries"][index] = asdict(claimed)
                conn.execute(
                    "UPDATE reconciliations SET body = ? WHERE accession_number = ?",
                    (json.dumps(body, ensure_ascii=False), accession_number),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return claimed

    def update_delivery(self, accession_number: str, index: int, **changes: Any) -> Delivery:
        """照合の `index` 番めの送信の記録を変える（組み立てた本文、送信の結果）.

        すでに受理（accepted）の送信は変えない。変えた後の記録を返す。
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT body FROM reconciliations WHERE accession_number = ?",
                    (accession_number,),
                ).fetchone()
                if row is None:
                    raise ReconciliationNotFoundError(
                        "Reconciliation not found", {"accession_number": accession_number}
                    )
                body = json.loads(row[0])
                current = Delivery(**body["deliveries"][index])
                if current.outcome == "accepted":
                    conn.execute("ROLLBACK")
                    return current
                updated = replace(current, **changes)
                body["deliveries"][index] = asdict(updated)
                conn.execute(
                    "UPDATE reconciliations SET body = ?, updated_at = ? WHERE accession_number = ?",
                    (json.dumps(body, ensure_ascii=False), _now(), accession_number),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return updated


def _select_mpps(conn: sqlite3.Connection, sop_instance_uid: str) -> tuple[Any, ...] | None:
    return conn.execute(
        "SELECT sop_instance_uid, status, accession_numbers, body, created_at, updated_at "
        "FROM mpps WHERE sop_instance_uid = ?",
        (sop_instance_uid,),
    ).fetchone()


def _mpps_record(row: Sequence[Any]) -> MppsRecord:
    return MppsRecord(
        sop_instance_uid=row[0],
        status=row[1],
        accession_numbers=json.loads(row[2]),
        body=json.loads(row[3]),
        created_at=row[4],
        updated_at=row[5],
    )


def _order_filter(
    date_from: str, date_to: str, statuses: list[OrderStatus] | None, modality: str, query: str = ""
) -> tuple[str, list[str | int]]:
    """一覧の条件の WHERE 句と値。空の条件は絞らない."""
    clauses: list[str] = []
    params: list[str | int] = []
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
    if query.strip():
        clauses.append("(patient_id = ? OR accession_number = ?)")
        params.extend([query.strip(), query.strip()])
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def _insert_order(conn: sqlite3.Connection, order: Order) -> None:
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


def _load_order(conn: sqlite3.Connection, accession_number: str) -> Order | None:
    row = conn.execute(
        "SELECT body FROM orders WHERE accession_number = ?", (accession_number,)
    ).fetchone()
    return Order.model_validate_json(row[0]) if row else None


def _orders_for_steps(
    conn: sqlite3.Connection, steps: Sequence[tuple[str, str] | tuple[str, str, str]],
    patient_id: str = "",
) -> list[Order]:
    """受付番号と SPS ID、または照合済みの Study UID と患者ID で探す（重ねない）."""
    orders: list[Order] = []
    for step in steps:
        accession_number, step_id = step[:2]
        study_uid = step[2] if len(step) == 3 else ""
        matches: list[Order] = []
        if accession_number:
            order = _load_order(conn, accession_number)
            if order is not None and step_id and order.scheduled_procedure_step_id == step_id:
                matches.append(order)
        elif study_uid and patient_id:
            # 照合の後も、モダリティが仮の患者のまま同じ Study で撮る（IHE PIR の Case 6）。
            # 照合で作った予約だけを相手にし、患者ID が仮か正式のどちらかと合うときだけ結ぶ
            rows = conn.execute(
                "SELECT orders.body FROM orders JOIN reconciliations "
                "ON orders.accession_number = reconciliations.accession_number "
                "WHERE json_extract(orders.body, '$.study_instance_uid') = ? "
                "AND (orders.patient_id = ? OR "
                "json_extract(reconciliations.body, '$.temporary.patient_id') = ?)",
                (study_uid, patient_id, patient_id),
            ).fetchall()
            matches = [Order.model_validate_json(row[0]) for row in rows]
        for order in matches:
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
