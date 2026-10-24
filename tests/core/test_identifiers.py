"""発番する識別子が DICOM・HL7 v2（IHE RAD-4）・FHIR R5 にそのまま入るかの試験（docs/spec/04_identifiers.md）."""

from __future__ import annotations

import re
from pathlib import Path

import pydantic
import pytest

from app.core.exceptions import ConfigurationError
from app.core.models import Patient, PersonName, is_valid_uid
from app.core.mwl_dataset import order_to_dataset
from app.services.order_service import OrderRequest, OrderService
from app.services.roster import load_roster
from tests.conftest import TODAY

# PS3.5 6.2 の SH（16 字）で、この RIS が発番する形（英数字だけ）
SH_IDENTIFIER = re.compile(r"[A-Za-z0-9]{1,16}")
# FHIR R5 の oid 型（datatypes.html）
FHIR_OID = re.compile(r"urn:oid:[0-2](\.(0|[1-9][0-9]*))+")
HL7_V2_DELIMITERS = set("|^~\\&")


def test_generated_identifiers_fit_every_standard(service: OrderService) -> None:
    orders = service.create_orders(
        OrderRequest(counts={"CT": 20, "MR": 20}, scheduled_date=TODAY, seed=7)
    )
    for order in orders:
        for value in (
            order.accession_number,
            order.requested_procedure_id,
            order.scheduled_procedure_step_id,
        ):
            # DICOM SH（PS3.5 6.2）、IHE RAD-4 の OBR-18・IPC-1 は 16 字まで（RAD TF-2 4.4.4.1.2）
            assert SH_IDENTIFIER.fullmatch(value), value
            assert not HL7_V2_DELIMITERS & set(value)
        patient_id = order.patient.patient_id
        # 乱数の患者ID は 15 字まで（接頭辞 8 字＋7 桁）、英数字だけ
        assert len(patient_id) <= 15 and patient_id.isascii() and patient_id.isalnum()

        uid = order.study_instance_uid
        # PS3.5 9.1 と B.2（2.25. + UUID の 10 進。39 桁まで）
        assert is_valid_uid(uid)
        assert uid.startswith("2.25.") and len(uid) <= 5 + 39
        # FHIR R5 ImagingStudy.identifier：system urn:dicom:uid、value urn:oid:<UID>
        assert FHIR_OID.fullmatch(f"urn:oid:{uid}")


def test_issuer_is_returned(service: OrderService) -> None:
    order = service.create_orders(OrderRequest(counts={"CR": 1}, scheduled_date=TODAY, seed=1))[0]
    ds = order_to_dataset(order)
    assert ds.IssuerOfPatientID == "RIS_EMU"
    assert ds.IssuerOfAccessionNumberSequence[0].LocalNamespaceEntityID == "RIS_EMU"


def test_issuer_can_be_turned_off(config, store) -> None:
    orders = config.orders.model_copy(update={"issuer_namespace": ""})
    service = OrderService(config.model_copy(update={"orders": orders}), store, today=lambda: TODAY)
    order = service.create_orders(OrderRequest(counts={"CR": 1}, scheduled_date=TODAY, seed=1))[0]
    ds = order_to_dataset(order)
    assert ds.IssuerOfPatientID in ("", None)
    assert len(ds.IssuerOfAccessionNumberSequence) == 0


@pytest.mark.parametrize("patient_id", ["P^1", "P|1", "P~1", "P&1", "P\\1", "P\t1", " P1", "P" * 65])
def test_patient_id_rules(patient_id: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        Patient(patient_id=patient_id, name=PersonName(alphabetic="A^B"))


def test_roster_with_hl7_delimiter_is_rejected(tmp_path: Path) -> None:
    roster = tmp_path / "roster.yaml"
    roster.write_text(
        'patients:\n  - patient_id: "P^001"\n    patient_name: {alphabetic: "A^B"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="patient_id"):
        load_roster(roster)


@pytest.mark.parametrize("uid", ["2.25.0123", "2.25.", "1..2", "2.25.a", "1.2." + "3" * 64])
def test_invalid_uids(uid: str) -> None:
    assert not is_valid_uid(uid)
