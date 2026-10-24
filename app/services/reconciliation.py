"""照合：予約の無い撮影（MPPS だけが記録された撮影）に、正式な患者と予約を結ぶ（docs/spec/07_reconciliation.md）."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import pydantic

from app.core.exceptions import AlreadyReconciledError, ReconciliationNotFoundError, ValidationError
from app.core.hl7 import (
    Hl7Message,
    build_adt_a08,
    build_adt_a40,
    build_orm_o01,
    visible,
)
from app.core.models import Order, Patient, PersonName, Procedure
from app.core.reconciliation import (
    MESSAGE_TYPES,
    DeliveryKind,
    UnreconciledMpps,
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

Sender = Callable[[Hl7Message, str, int, float], DeliveryResult]


@dataclass(frozen=True)
class ReconcileRequest:
    """照合の指定。検査名と依頼科を省くと、検査名はモダリティの先頭、依頼科は救急科（無ければ先頭）."""

    sop_instance_uid: str
    patient: Patient
    procedure_code: str | None = None
    department: str | None = None


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

    def reconcile(self, request: ReconcileRequest) -> Reconciliation:
        """正式な患者と新しい予約を結び、HL7 を送る.

        予約・結び付け・送る HL7 の組み立てを1つのトランザクションで行い（誤りがあれば何も
        残さない）、その後で HL7 を順に送る。送信が失敗・拒否でも照合は取り消さない。
        """
        unreconciled, linked = self.get_mpps(request.sop_instance_uid)
        if linked:
            raise AlreadyReconciledError(
                "この撮影はすでに予約に結び付いています",
                {"sop_instance_uid": request.sop_instance_uid, "accession_number": linked[0]},
            )
        if unreconciled.problem:
            raise ValidationError(f"照合できません：{unreconciled.problem}")
        if request.patient.birth_date:
            try:
                datetime.strptime(request.patient.birth_date, "%Y%m%d")
            except ValueError as exc:
                raise ValidationError(
                    f"生年月日が実在する日付ではありません: {request.patient.birth_date}"
                ) from exc
        if unreconciled.modality not in self.config.orders.modalities:
            raise ValidationError(
                f"MPPS のモダリティ {unreconciled.modality or '（空）'} が設定に無いので、照合できません"
            )
        kinds = plan_deliveries(
            unreconciled.patient,
            request.patient.patient_id,
            request.patient.name,
            request.patient.birth_date,
            request.patient.sex,
        )
        procedure = self._procedure(unreconciled.modality, request.procedure_code)
        department = self._department(request.department)
        created = self.orders.today()
        temporary = {
            "patient_id": unreconciled.patient.patient_id,
            "alphabetic": unreconciled.patient.name.alphabetic,
            "ideographic": unreconciled.patient.name.ideographic,
            "phonetic": unreconciled.patient.name.phonetic,
            "birth_date": unreconciled.patient.birth_date,
            "sex": unreconciled.patient.sex,
        }

        def build(sequence: int, record: MppsRecord) -> tuple[Order, list[Delivery]]:
            order = self._build_order(
                sequence, read_unreconciled(**_fields(record)), request.patient, procedure, department
            )
            return order, [self._build_delivery(kind, order, temporary) for kind in kinds]

        order = self.store.reconcile_mpps(
            f"accession:{created:%Y%m%d}", request.sop_instance_uid, build, temporary
        )
        return self.send_pending(order.accession_number)

    def send_pending(self, accession_number: str) -> Reconciliation:
        """未送信・失敗・拒否の HL7 を順に送る。受理されなかった1通で止める（次の通は送らない）."""
        reconciliation = self._get(accession_number)
        for index, delivery in enumerate(reconciliation.deliveries):
            if delivery.outcome == "accepted":
                continue
            if self._deliver(accession_number, index, delivery) != "accepted":
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
            attempts=delivery.attempts + 1,
            sent_at=sent_at,
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
            raise ValidationError(f"予約の値が正しくありません: {location}: {first['msg']}") from exc
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
                now=now,
            )
        return Delivery(
            kind=kind,
            message_type=MESSAGE_TYPES[kind],
            control_id=message.control_id,
            text=message.text,
        )


def _read(record: MppsRecord) -> UnreconciledMpps:
    return read_unreconciled(**_fields(record))


def _fields(record: MppsRecord) -> dict[str, object]:
    return {
        "sop_instance_uid": record.sop_instance_uid,
        "status": record.status,
        "received_at": record.created_at,
        "body": record.body,
    }
