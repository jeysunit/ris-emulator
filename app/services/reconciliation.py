"""照合：予約の無い撮影（MPPS だけが記録された撮影）に、正式な患者と予約を結ぶ（docs/spec/07_reconciliation.md）."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import pydantic

from app.core.exceptions import (
    AlreadyReconciledError,
    ConfigurationError,
    ReconciliationNotFoundError,
    ValidationError,
)
from app.core.hl7 import (
    Hl7Message,
    build_adt_a08,
    build_adt_a40,
    build_orm_o01,
    visible,
)
from app.core.models import Order, OrderStatus, Patient, PersonName, Procedure
from app.core.reconciliation import (
    MESSAGE_TYPES,
    ORDER_CONTROLS,
    STATUS_DELIVERIES,
    DeliveryKind,
    UnreconciledMpps,
    looks_like_another_patient,
    plan_deliveries,
    read_unreconciled,
)
from app.hl7.mllp import DeliveryResult, send_message

from .order_service import (
    DAILY_SEQUENCE_MAX,
    OrderService,
    _check_lo_text,
    check_encodable,
)
from .store import Delivery, MppsRecord, Reconciliation

# 照合で作る予約の PV1-2（HL7 Table 0004 の E=救急）と優先度。予約の無い撮影は緊急の飛び込み
PATIENT_CLASS_EMERGENCY = "E"
PRIORITY_EMERGENCY = "STAT"
DEFAULT_DEPARTMENT = "救急科"
# 送信の権利（claim_delivery）の有効な時間は、送信の時間切れの 2 倍にこの秒数を足したもの
CLAIM_MARGIN_SECONDS = 5.0
# 予約の状態 → 照合で作った予約をその状態に変えたときに送る通の種類とメッセージ型（画面の確認の窓）
STATUS_MESSAGES: dict[OrderStatus, tuple[DeliveryKind, str]] = {
    status: (kind, MESSAGE_TYPES[kind]) for status, kind in STATUS_DELIVERIES.items()
}

Sender = Callable[[Hl7Message, str, int, float], DeliveryResult]


@dataclass(frozen=True)
class ReconcileRequest:
    """照合の指定。検査名と依頼科を省くと、検査名はモダリティの先頭、依頼科は救急科（無ければ先頭）."""

    sop_instance_uid: str
    patient: Patient
    procedure_code: str | None = None
    department: str | None = None
    # 確認の窓で見せた内容の鍵（ReconcilePreview.key）。与えると、確定のときに読み直した撮影で
    # 作った鍵と違えば断る（確かめた後に仮の患者や送る通が変わっていたら、確かめ直させる）
    confirmed_key: str | None = None


@dataclass(frozen=True)
class ReconcilePreview:
    """照合を確定する前に見せる内容：仮の患者（撮影）、送る HL7 の種類、検査名、依頼科."""

    unreconciled: UnreconciledMpps
    deliveries: tuple[DeliveryKind, ...]
    procedure: Procedure
    department: str
    key: str

    @property
    def message_types(self) -> list[str]:
        return [MESSAGE_TYPES[kind] for kind in self.deliveries]


class ReconciliationService:
    def __init__(self, orders: OrderService, send: Sender = send_message):
        self.orders = orders
        self.store = orders.store
        self.config = orders.config
        self._send = send

    def list_unreconciled(self) -> list[UnreconciledMpps]:
        """予約に結び付かなかった MPPS を、受けた順に返す."""
        return [_read(record) for record in self.store.list_unlinked_mpps()]

    def get_mpps(self, sop_instance_uid: str) -> tuple[UnreconciledMpps, list[str]]:
        """MPPS から読み取った値と、結び付いた予約の受付番号（照合済みなら空でない）."""
        record = self.store.get_mpps(sop_instance_uid)
        return _read(record), record.accession_numbers

    def procedures_for(self, modality: str) -> list[Procedure]:
        entry = self.config.orders.modalities.get(modality)
        return list(entry.procedures) if entry else []

    def preview(self, request: ReconcileRequest) -> ReconcilePreview:
        """照合を確定せずに、確認の窓に出す内容を返す。照合できなければ `reconcile` と同じ例外."""
        unreconciled = self._unlinked(request.sop_instance_uid)
        self._check(unreconciled, request.patient)
        procedure = self._procedure(unreconciled.modality, request.procedure_code)
        department = self._department(request.department)
        kinds = tuple(_plan(unreconciled, request.patient))
        return ReconcilePreview(
            unreconciled=unreconciled,
            deliveries=kinds,
            procedure=procedure,
            department=department,
            key=_confirmation_key(unreconciled, request.patient, kinds, procedure, department),
        )

    def known_patients(self, patient_id: str) -> list[Patient]:
        """同じ患者ID を持つ、名簿と予約の患者（同じ値の重なりを除く）.

        名簿が読めなければ ConfigurationError（名簿にだけある患者を見落とさないよう、予約だけで
        済ませない）。
        """
        try:
            roster = self.orders.roster_patients()
        except ConfigurationError as exc:
            raise ConfigurationError(
                "名簿を読めないので、患者ID が既にある患者のものかを確かめられません。"
                "名簿を直してから照合してください",
                exc.details,
            ) from exc
        found = [p for p in roster if p.patient_id == patient_id]
        found += [
            order.patient
            for order in self.orders.list_orders(query=patient_id)
            if order.patient.patient_id == patient_id
        ]
        unique: list[Patient] = []
        for patient in found:
            if patient not in unique:
                unique.append(patient)
        return unique

    @staticmethod
    def another_patient(patient: Patient, known: list[Patient]) -> Patient | None:
        """`known`（同じ患者ID の既にある患者）のうち、`patient` と別人に見える最初の患者."""
        return next((p for p in known if looks_like_another_patient(p, patient)), None)

    def reconcile(self, request: ReconcileRequest) -> Reconciliation:
        """正式な患者と新しい予約を結び、HL7 を送る.

        予約・結び付け・送る HL7 の組み立てを1つのトランザクションで行い（誤りがあれば何も
        残さない）、その後で HL7 を順に送る。送信が失敗・拒否でも照合は取り消さない。
        """
        unreconciled = self._unlinked(request.sop_instance_uid)
        self._check(unreconciled, request.patient)
        procedure = self._procedure(unreconciled.modality, request.procedure_code)
        department = self._department(request.department)
        created = self.orders.today()

        def build(
            sequence: int, record: MppsRecord
        ) -> tuple[Order, list[Delivery], dict[str, str]]:
            # 結び付ける MPPS をトランザクションの中で読み直した値から、予約・送る HL7・仮の患者を
            # 作る（N-SET が間に入っても、旧い患者ID と送る種類が予約と食い違わない）
            current = read_unreconciled(**_fields(record))
            self._check(current, request.patient)
            temporary = {
                "patient_id": current.patient.patient_id,
                "alphabetic": current.patient.name.alphabetic,
                "ideographic": current.patient.name.ideographic,
                "phonetic": current.patient.name.phonetic,
                "birth_date": current.patient.birth_date,
                "sex": current.patient.sex,
            }
            kinds = _plan(current, request.patient)
            if request.confirmed_key is not None and request.confirmed_key != _confirmation_key(
                current, request.patient, tuple(kinds), procedure, department
            ):
                raise ValidationError(
                    "確かめた後に、撮影の値か送る HL7 が変わりました。内容を確かめ直してください"
                )
            order = self._build_order(sequence, current, request.patient, procedure, department)
            deliveries = [self._build_delivery(kind, order, temporary) for kind in kinds]
            return order, deliveries, temporary

        order = self.store.reconcile_mpps(
            f"accession:{created:%Y%m%d}", request.sop_instance_uid, build
        )
        return self.send_pending(order.accession_number)

    def set_status(
        self, accession_number: str, status: OrderStatus
    ) -> tuple[Order, Reconciliation | None]:
        """画面・CLI の状態の変更。照合で作った予約を取消・中止したら、ORM（CA・DC）を足して送る.

        状態の変更と送る通の追加は 1 つのトランザクションで行う。前の通が受理されていなければ
        何も送らず、足した通は送信待ちで残る（予約を知らせる前に取消を送らない。前の通の送り直しは
        再送信の操作で行う）。
        MPPS（N-SET）による中止では送らない（モダリティの MPPS は PACS も受けるため）。
        通を足さなかったときの 2 つめの値は None。
        """
        added = False

        def build(order: Order) -> Delivery | None:
            nonlocal added
            kind = STATUS_DELIVERIES.get(order.status)
            if kind is None:
                return None
            added = True
            return self._build_delivery(kind, order, {})

        order = self.store.set_status(accession_number, status, build)
        if not added:
            return order, None
        reconciliation = self._get(accession_number)
        if any(d.outcome != "accepted" for d in reconciliation.deliveries[:-1]):
            # 前の通の送り直しは、再送信の操作に任せる（足した通は送信待ちで残す）
            return order, reconciliation
        return order, self.send_pending(accession_number)

    def _unlinked(self, sop_instance_uid: str) -> UnreconciledMpps:
        """予約に結び付いていない撮影。結び付いていれば AlreadyReconciledError."""
        unreconciled, linked = self.get_mpps(sop_instance_uid)
        if linked:
            raise AlreadyReconciledError(
                "この撮影はすでに予約に結び付いています",
                {"sop_instance_uid": sop_instance_uid, "accession_number": linked[0]},
            )
        return unreconciled

    def _check(self, unreconciled: UnreconciledMpps, patient: Patient) -> None:
        """照合できる撮影と患者か。できなければ ValidationError."""
        if unreconciled.problem:
            raise ValidationError(f"照合できません：{unreconciled.problem}")
        if patient.birth_date:
            try:
                datetime.strptime(patient.birth_date, "%Y%m%d")
            except ValueError as exc:
                raise ValidationError(
                    f"生年月日が実在する日付ではありません: {patient.birth_date}"
                ) from exc
        if unreconciled.modality not in self.config.orders.modalities:
            raise ValidationError(
                f"MPPS のモダリティ {unreconciled.modality or '（空）'} が設定に無いので、照合できません"
            )

    def send_pending(self, accession_number: str) -> Reconciliation:
        """未送信・失敗・拒否の HL7 を順に送る。受理されなかった1通で止める（次の通は送らない）.

        他のプロセスが同じ通を送っている間は、その通を送らずに止める。
        """
        reconciliation = self._get(accession_number)
        lease = self.config.hl7.timeout_seconds * 2 + CLAIM_MARGIN_SECONDS
        for index, delivery in enumerate(reconciliation.deliveries):
            if delivery.outcome == "accepted":
                continue
            claimed = self.store.claim_delivery(accession_number, index, time.time(), lease)
            if claimed is None or self._deliver(accession_number, index, claimed) != "accepted":
                break
        return self._get(accession_number)

    def _deliver(self, accession_number: str, index: int, delivery: Delivery) -> str:
        hl7 = self.config.hl7
        message = Hl7Message(delivery.message_type, delivery.control_id, delivery.text)
        result = self._send(message, hl7.host, hl7.port, hl7.timeout_seconds)
        sent_at = self.orders.now().astimezone().isoformat(timespec="seconds")
        # 相手の ACK の値は、画面と記録に出す前に、制御文字を見える形にする
        detail = result.detail
        if result.outcome == "rejected" and not detail:
            detail = result.ack_text
        self.store.update_delivery(
            accession_number,
            index,
            outcome=result.outcome,
            ack_code=visible(result.ack_code),
            detail=visible(detail),
            sent_at=sent_at,
            claimed_at=0.0,
        )
        return result.outcome

    def _get(self, accession_number: str) -> Reconciliation:
        reconciliation = self.store.get_reconciliation(accession_number)
        if reconciliation is None:
            raise ReconciliationNotFoundError(
                "Reconciliation not found", {"accession_number": accession_number}
            )
        return reconciliation

    def get_reconciliation(self, accession_number: str) -> Reconciliation | None:
        return self.store.get_reconciliation(accession_number)

    def _procedure(self, modality: str, code: str | None) -> Procedure:
        procedures = self.config.orders.modalities[modality].procedures
        if code is None:
            return procedures[0]
        found = next((p for p in procedures if p.code == code), None)
        if found is None:
            raise ValidationError(f"{modality} の検査の種類に無いコードです: {code}")
        return found

    def _department(self, department: str | None) -> str:
        if department is None:
            departments = self.config.orders.departments
            return DEFAULT_DEPARTMENT if DEFAULT_DEPARTMENT in departments else departments[0]
        _check_lo_text("依頼科", department)
        return department

    def _build_order(
        self,
        sequence: int,
        unreconciled: UnreconciledMpps,
        patient: Patient,
        procedure: Procedure,
        department: str,
    ) -> Order:
        if sequence > DAILY_SEQUENCE_MAX:
            raise ValidationError(f"1 日に作れる予約は {DAILY_SEQUENCE_MAX} 件までです")
        orders = self.config.orders
        created = self.orders.today()
        now = self.orders.now()
        number = f"{created:%Y%m%d}{sequence:04d}"
        entry = orders.modalities[unreconciled.modality]
        station = next(
            (s for s in entry.stations if s.ae_title == unreconciled.station_ae_title), None
        )
        if station is None and not unreconciled.station_ae_title:
            station = entry.stations[0]
        try:
            order = Order(
                accession_number=f"{orders.accession_prefix}{number}",
                requested_procedure_id=f"RP{number}",
                scheduled_procedure_step_id=f"SPS{number}",
                # 撮影が持つ値をそのまま使う。新しく発番しない（PIR では Study UID が照合の鍵）
                study_instance_uid=unreconciled.study_instance_uid,
                issuer_namespace=orders.issuer_namespace,
                patient=patient,
                modality=unreconciled.modality,
                scheduled_station_ae_title=station.ae_title if station else unreconciled.station_ae_title,
                scheduled_station_name=station.station_name if station else unreconciled.station_name,
                scheduled_station_label=station.name if station else "",
                scheduled_date=unreconciled.started_date or created.strftime("%Y%m%d"),
                scheduled_time=unreconciled.started_time or now.strftime("%H%M%S"),
                procedure=procedure,
                requesting_service=department,
                institution_name=orders.institution_name,
                priority=PRIORITY_EMERGENCY,
                character_set=orders.default_character_set,
            )
        except pydantic.ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first["loc"])
            raise ValidationError(f"予約の値を受け付けられません: {location}: {first['msg']}") from exc
        check_encodable(order)
        return order

    def _build_delivery(self, kind: DeliveryKind, order: Order, temporary: dict[str, str]) -> Delivery:
        header = self.config.hl7.header()
        now = self.orders.now()
        namespace = self.config.orders.issuer_namespace
        if kind == "a40":
            prior = PersonName(
                alphabetic=temporary["alphabetic"],
                ideographic=temporary["ideographic"],
                phonetic=temporary["phonetic"],
            )
            message = build_adt_a40(
                header,
                order.patient,
                namespace=namespace,
                prior_patient_id=temporary["patient_id"],
                prior_name=prior,
                now=now,
            )
        elif kind == "a08":
            message = build_adt_a08(
                header,
                order.patient,
                namespace=namespace,
                visit_number=order.accession_number,
                patient_class=PATIENT_CLASS_EMERGENCY,
                now=now,
            )
        else:
            message = build_orm_o01(
                header,
                order,
                visit_number=order.accession_number,
                patient_class=PATIENT_CLASS_EMERGENCY,
                order_control=ORDER_CONTROLS[kind],
                now=now,
            )
        return Delivery(
            kind=kind,
            message_type=MESSAGE_TYPES[kind],
            control_id=message.control_id,
            text=message.text,
        )


def _plan(unreconciled: UnreconciledMpps, patient: Patient) -> list[DeliveryKind]:
    return plan_deliveries(
        unreconciled.patient, patient.patient_id, patient.name, patient.birth_date, patient.sex
    )


def _confirmation_key(
    unreconciled: UnreconciledMpps,
    patient: Patient,
    kinds: tuple[DeliveryKind, ...],
    procedure: Procedure,
    department: str,
) -> str:
    """確認の窓に出した内容（仮の患者・正式な患者・送る通・検査名・依頼科）の鍵."""
    temporary = unreconciled.patient
    shown = [
        list(kinds),
        [temporary.patient_id, temporary.name.to_dicom(), temporary.birth_date, temporary.sex],
        [patient.patient_id, patient.name.to_dicom(), patient.birth_date, patient.sex],
        [unreconciled.study_instance_uid, unreconciled.modality, procedure.code, department],
    ]
    text = json.dumps(shown, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _read(record: MppsRecord) -> UnreconciledMpps:
    return read_unreconciled(**_fields(record))


def _fields(record: MppsRecord) -> dict[str, object]:
    return {
        "sop_instance_uid": record.sop_instance_uid,
        "status": record.status,
        "received_at": record.created_at,
        "body": record.body,
    }
