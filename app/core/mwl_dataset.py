"""予約から MWL の応答の Identifier を組み立てる（spec/02_mwl_scp.md 4 章）.

出典は DICOM PS3.4 Table K.6-1（Modality Worklist の属性）と、
K.4.1.1.3.2（応答には要求に入っていた属性だけを入れる）。Pure な処理。
"""

from __future__ import annotations

from pydicom.datadict import dictionary_VR
from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from .models import CHARACTER_SET_TERMS, SPS_STATUS_TERMS, Order

# 要求に入っていても照合と応答の対象にしない属性（PS3.4 K.6-1a。Specific Character Set は照合しない）
NON_KEY_TAGS = frozenset({0x00080005, 0x00080201})


def order_to_dataset(order: Order) -> Dataset:
    """予約の1件を、この SCP が持つ属性をすべて入れた Dataset にする."""
    ds = Dataset()
    terms = CHARACTER_SET_TERMS[order.character_set]
    ds.SpecificCharacterSet = terms if len(terms) > 1 else terms[0]

    # Patient Identification・Demographic
    patient = order.patient
    ds.PatientName = patient.name.to_dicom()
    ds.PatientID = patient.patient_id
    ds.IssuerOfPatientID = order.issuer_namespace
    ds.PatientBirthDate = patient.birth_date
    ds.PatientSex = patient.sex
    ds.PatientWeight = _decimal(patient.weight_kg)
    ds.PatientSize = _decimal(patient.size_m)

    # Imaging Service Request
    ds.AccessionNumber = order.accession_number
    ds.IssuerOfAccessionNumberSequence = Sequence(_issuer_items(order.issuer_namespace))
    ds.RequestingPhysician = order.requesting_physician.to_dicom()
    ds.ReferringPhysicianName = order.referring_physician.to_dicom()
    ds.RequestingService = order.requesting_service
    ds.InstitutionName = order.institution_name

    # Requested Procedure
    ds.RequestedProcedureID = order.requested_procedure_id
    ds.RequestedProcedureDescription = order.procedure.name
    ds.RequestedProcedureCodeSequence = Sequence([_code_item(order)])
    ds.StudyInstanceUID = order.study_instance_uid
    ds.ReferencedStudySequence = Sequence()
    ds.RequestedProcedurePriority = order.priority
    ds.PatientTransportArrangements = ""
    ds.ReasonForTheRequestedProcedure = ""

    # Visit・Patient Medical など（Table K.6-1 の Return Key Type 2。値は持たない）
    ds.AdmissionID = ""
    ds.CurrentPatientLocation = ""
    ds.ReferencedPatientSequence = Sequence()
    ds.ConfidentialityConstraintOnPatientDataDescription = ""
    ds.PatientState = ""
    ds.PregnancyStatus = None
    ds.MedicalAlerts = ""
    ds.Allergies = ""
    ds.SpecialNeeds = ""

    # Scheduled Procedure Step（1件に1つ。PS3.4 K.6-1）
    sps = Dataset()
    sps.ScheduledStationAETitle = order.scheduled_station_ae_title
    sps.ScheduledStationName = order.scheduled_station_name
    sps.ScheduledProcedureStepStartDate = order.scheduled_date
    sps.ScheduledProcedureStepStartTime = order.scheduled_time
    sps.Modality = order.modality
    sps.ScheduledPerformingPhysicianName = order.scheduled_performing_physician.to_dicom()
    sps.ScheduledProcedureStepDescription = order.procedure.name
    sps.ScheduledProtocolCodeSequence = Sequence([_code_item(order)])
    sps.ScheduledProcedureStepID = order.scheduled_procedure_step_id
    sps.ScheduledProcedureStepLocation = ""
    sps.PreMedication = ""
    sps.RequestedContrastAgent = ""
    status_term = SPS_STATUS_TERMS.get(order.status)
    if status_term:
        sps.ScheduledProcedureStepStatus = status_term
    ds.ScheduledProcedureStepSequence = Sequence([sps])
    return ds


def build_response(full: Dataset, request: Dataset) -> Dataset:
    """要求の属性だけを持つ応答の Identifier を作る（PS3.4 K.4.1.1.3.2）.

    - 要求にあってこの SCP が持つ属性は値を返す
    - 要求にあって持たない属性は空の値で返す（Type 2 と同じ扱い）
    - Sequence は、要求の項目が空なら全部の属性を、属性があればその属性だけを返す
    - Specific Character Set は予約の値を入れる
    """
    response = _filter(full, request)
    if "SpecificCharacterSet" in full:
        response.SpecificCharacterSet = full.SpecificCharacterSet
    return response


def has_unsupported_keys(full: Dataset, request: Dataset) -> bool:
    """要求に、この SCP が持たない属性があるか（あれば Pending を FF01 にする。PS3.4 Table K.4-1）."""
    for element in request:
        if element.tag in NON_KEY_TAGS or element.tag.is_private:
            continue
        if element.tag not in full:
            return True
        source = full[element.tag]
        if element.VR == "SQ" and source.VR == "SQ":
            request_items = list(element.value or [])
            if request_items and any(
                has_unsupported_keys(item, request_items[0]) for item in source.value
            ):
                return True
    return False


def _filter(full: Dataset, request: Dataset) -> Dataset:
    out = Dataset()
    for element in request:
        if element.tag in NON_KEY_TAGS or element.tag.is_private:
            continue
        if element.tag not in full:
            out.add(_empty_element(element))
            continue
        source = full[element.tag]
        if source.VR != "SQ":
            out.add(DataElement(source.tag, source.VR, source.value))
            continue
        request_items = list(element.value or [])
        if not request_items or len(request_items[0]) == 0:
            out.add(DataElement(source.tag, "SQ", Sequence([_copy(item) for item in source.value])))
        else:
            items = [_filter(item, request_items[0]) for item in source.value]
            out.add(DataElement(source.tag, "SQ", Sequence(items)))
    return out


def _empty_element(element: DataElement) -> DataElement:
    vr = element.VR
    if vr in ("UN", "") or vr is None:
        try:
            vr = dictionary_VR(element.tag)
        except KeyError:
            vr = "UN"
    if vr == "SQ":
        return DataElement(element.tag, "SQ", Sequence())
    return DataElement(element.tag, vr, None)


def _copy(item: Dataset) -> Dataset:
    out = Dataset()
    for element in item:
        if element.VR == "SQ":
            out.add(DataElement(element.tag, "SQ", Sequence([_copy(i) for i in element.value])))
        else:
            out.add(DataElement(element.tag, element.VR, element.value))
    return out


def _issuer_items(namespace: str) -> list[Dataset]:
    """Issuer of Accession Number Sequence の項目（HL7v2 Hierarchic Designator Macro。PS3.3 Table 10-17）."""
    if not namespace:
        return []
    item = Dataset()
    item.LocalNamespaceEntityID = namespace
    return [item]


def _code_item(order: Order) -> Dataset:
    item = Dataset()
    item.CodeValue = order.procedure.code
    item.CodingSchemeDesignator = order.procedure.coding_scheme
    item.CodeMeaning = order.procedure.name
    return item


def _decimal(value: float | None) -> str:
    """DS の文字列（16 字まで）。値が無ければ空."""
    if value is None:
        return ""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text[:16]
