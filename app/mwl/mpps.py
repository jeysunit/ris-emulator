"""MPPS（Modality Performed Procedure Step）の N-CREATE・N-SET の処理（docs/spec/05_mpps_scp.md）.

出典は DICOM PS3.4 F.7.2（N-CREATE・N-SET の SCP の動作）、PS3.3 C.4.14
（Performed Procedure Step Status）、PS3.7 C.5（ステータス）。ネットワークから切り離した
処理で、`app/mwl/server.py` の handler から呼ぶ。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydicom.dataset import Dataset

from app.core.exceptions import DuplicateMppsError, MppsNotFoundError, MppsNotInProgressError
from app.core.models import is_valid_uid
from app.services.store import PPS_IN_PROGRESS, PPS_STATUSES, MppsResult, OrderStore

logger = logging.getLogger(__name__)

STATUS_SUCCESS = 0x0000
STATUS_INVALID_ATTRIBUTE_VALUE = 0x0106  # PS3.7 C.5.11
STATUS_PROCESSING_FAILURE = 0x0110  # PS3.7 C.5.21
STATUS_DUPLICATE_SOP_INSTANCE = 0x0111  # PS3.7 C.5.8
STATUS_NO_SUCH_SOP_INSTANCE = 0x0112  # PS3.7 C.5.19
STATUS_MISSING_ATTRIBUTE = 0x0120
# PS3.4 Table F.7.2-2：IN PROGRESS でない MPPS への N-SET
ERROR_ID_NO_LONGER_UPDATED = 0xA710
UID_ROOT = "2.25"

Response = tuple[int | Dataset, Dataset | None]


def handle_n_create(store: OrderStore, sop_instance_uid: str | None, attributes: Dataset) -> Response:
    """N-CREATE を処理して (Status, 応答の Attribute List) を返す.

    SOP Instance UID が要求に無ければ SCP が発番し、応答の Affected SOP Instance UID で
    返す（PS3.7 10.1.5.1.4）。pynetdicom は、要求に UID が無いときだけ、handler が返した
    Dataset の AffectedSOPInstanceUID を応答の Command Set に移す。
    """
    reply: Dataset | None = None
    if sop_instance_uid is None:
        sop_instance_uid = f"{UID_ROOT}.{uuid.uuid4().int}"
        reply = Dataset()
        reply.AffectedSOPInstanceUID = sop_instance_uid
    elif not is_valid_uid(str(sop_instance_uid)):
        logger.warning("MPPS N-CREATE refused: invalid SOP Instance UID %r", sop_instance_uid)
        return STATUS_INVALID_ATTRIBUTE_VALUE, None
    sop_instance_uid = str(sop_instance_uid)

    if "PerformedProcedureStepStatus" not in attributes:
        logger.warning("MPPS N-CREATE %s refused: no Performed Procedure Step Status", sop_instance_uid)
        return STATUS_MISSING_ATTRIBUTE, None
    status = str(attributes.PerformedProcedureStepStatus or "").strip()
    if status != PPS_IN_PROGRESS:
        # PS3.4 F.7.2.1.3：IN PROGRESS 以外の N-CREATE は 0106H
        logger.warning("MPPS N-CREATE %s refused: status %r", sop_instance_uid, status)
        return STATUS_INVALID_ATTRIBUTE_VALUE, None
    if "ScheduledStepAttributesSequence" not in attributes:
        logger.warning("MPPS N-CREATE %s refused: no Scheduled Step Attributes Sequence", sop_instance_uid)
        return STATUS_MISSING_ATTRIBUTE, None

    steps = [
        (_text(item, "AccessionNumber"), _text(item, "ScheduledProcedureStepID"))
        for item in attributes.ScheduledStepAttributesSequence or []
    ]
    try:
        result = store.create_mpps(sop_instance_uid, steps, attributes.to_json_dict())
    except DuplicateMppsError:
        logger.warning("MPPS N-CREATE %s refused: duplicate SOP Instance", sop_instance_uid)
        return STATUS_DUPLICATE_SOP_INSTANCE, None
    _log_result("N-CREATE", sop_instance_uid, PPS_IN_PROGRESS, result)
    return STATUS_SUCCESS, reply


def handle_n_set(store: OrderStore, sop_instance_uid: str, modifications: Dataset) -> Response:
    """N-SET を処理して (Status, 応答の Attribute List) を返す."""
    sop_instance_uid = str(sop_instance_uid)
    status: str | None = None
    if "PerformedProcedureStepStatus" in modifications:
        status = str(modifications.PerformedProcedureStepStatus or "").strip()
        if status not in PPS_STATUSES:
            logger.warning("MPPS N-SET %s refused: status %r", sop_instance_uid, status)
            return STATUS_INVALID_ATTRIBUTE_VALUE, None
    try:
        result = store.update_mpps(sop_instance_uid, status, modifications.to_json_dict())
    except MppsNotFoundError:
        logger.warning("MPPS N-SET %s refused: no such SOP Instance", sop_instance_uid)
        return STATUS_NO_SUCH_SOP_INSTANCE, None
    except MppsNotInProgressError as exc:
        # PS3.4 F.7.2.2.3・Table F.7.2-2
        logger.warning("MPPS N-SET %s refused: %s", sop_instance_uid, exc)
        failure = Dataset()
        failure.Status = STATUS_PROCESSING_FAILURE
        failure.ErrorComment = "Performed Procedure Step Object may no longer be updated"
        failure.ErrorID = ERROR_ID_NO_LONGER_UPDATED
        return failure, None
    _log_result("N-SET", sop_instance_uid, status or "(no status)", result)
    return STATUS_SUCCESS, None


def _text(item: Dataset, keyword: str) -> str:
    value: Any = item.get(keyword)
    return str(value).strip() if value is not None else ""


def _log_result(operation: str, sop_instance_uid: str, status: str, result: MppsResult) -> None:
    logger.info(
        "MPPS %s %s (%s): linked=%s changed=%s",
        operation,
        sop_instance_uid,
        status,
        result.linked or "-",
        result.changed or "-",
    )
    for accession_number, current in result.unchanged:
        # 終わりの状態の予約、または遷移の表に無い向き。MPPS は記録し、予約は変えない
        logger.warning(
            "MPPS %s %s: order %s stays %s (transition not allowed)",
            operation,
            sop_instance_uid,
            accession_number,
            current.value,
        )
