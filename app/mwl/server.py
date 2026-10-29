"""MWL と MPPS の SCP（pynetdicom。ADR-0001・ADR-0007、docs/spec/02_mwl_scp.md・05_mpps_scp.md）.

C-FIND（Modality Worklist Information Model - FIND、1.2.840.10008.5.1.4.31）、
N-CREATE・N-SET（Modality Performed Procedure Step、1.2.840.10008.3.1.2.3.3）と
C-ECHO（Verification）を受ける。予約は要求のたびに保存先から読み直す。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind,
    Verification,
)

from app.core.exceptions import MwlServerError
from app.core.matching import has_matching_keys, matches
from app.core.mwl_dataset import build_response, has_unsupported_keys, order_to_dataset
from app.mwl.mpps import STATUS_PROCESSING_FAILURE, handle_n_create, handle_n_set
from app.services.config import MwlConfig
from app.services.store import OrderStore

logger = logging.getLogger(__name__)

STATUS_PENDING = 0xFF00
STATUS_PENDING_WARNING = 0xFF01
STATUS_SUCCESS = 0x0000
STATUS_CANCEL = 0xFE00
STATUS_OUT_OF_RESOURCES = 0xA700
STATUS_UNABLE_TO_PROCESS = 0xC001

# 画面の「接続確認」が自分の待ち受けにかける C-ECHO の、呼び元の AEタイトルと待つ秒数
ECHO_CALLING_AE_TITLE = "RIS_CHECK"
ECHO_TIMEOUT_SECONDS = 3.0

_WILDCARD_TO_LOOPBACK = {"0.0.0.0": "127.0.0.1", "::": "::1"}


def _loopback_of(bind_address: str) -> str:
    """待ち受けのアドレスへつなぐ住所（全部のアドレスで待ち受けているときはループバック）."""
    return _WILDCARD_TO_LOOPBACK.get(bind_address, bind_address)


def find_worklist(
    request: Dataset, store: OrderStore, config: MwlConfig
) -> tuple[int, list[tuple[int, Dataset]]]:
    """要求に合う予約の応答を作る.

    戻り値は (最後の状態, Pending の状態と応答の並び)。要求にこの SCP が持たない
    属性があれば、その応答の Pending は FF01（PS3.4 Table K.4-1）。
    """
    if not has_matching_keys(request):
        return STATUS_SUCCESS, []
    responses: list[tuple[int, Dataset]] = []
    for order in store.list_orders(statuses=list(config.statuses)):
        full = order_to_dataset(order)
        if matches(full, request):
            status = (
                STATUS_PENDING_WARNING if has_unsupported_keys(full, request) else STATUS_PENDING
            )
            responses.append((status, build_response(full, request)))
            if len(responses) > config.max_results:
                logger.warning("C-FIND matches over max_results=%s; refused", config.max_results)
                return STATUS_OUT_OF_RESOURCES, []
    return STATUS_SUCCESS, responses


class MwlServer:
    """MWL の SCP。`start()` で別のスレッドで待ち受け、`stop()` で止める."""

    def __init__(self, config: MwlConfig, store: OrderStore):
        self.config = config
        self.store = store
        self._server: Any = None

    def make_ae(self) -> AE:
        ae = AE(ae_title=self.config.ae_title)
        ae.require_called_aet = self.config.require_called_ae_title
        ae.add_supported_context(ModalityWorklistInformationFind)
        ae.add_supported_context(ModalityPerformedProcedureStep)
        ae.add_supported_context(Verification)
        return ae

    @property
    def handlers(self) -> list[tuple[Any, Any]]:
        return [
            (evt.EVT_C_FIND, self._handle_find),
            (evt.EVT_N_CREATE, self._handle_n_create),
            (evt.EVT_N_SET, self._handle_n_set),
        ]

    def start(self) -> None:
        if self._server is not None:
            return
        try:
            self._server = self.make_ae().start_server(
                (self.config.bind_address, self.config.port),
                block=False,
                evt_handlers=self.handlers,
            )
        except OSError as exc:
            raise MwlServerError(
                "MWL SCP could not listen",
                {"address": self.config.bind_address, "port": self.config.port, "error": str(exc)},
            ) from exc
        logger.info(
            "MWL SCP %s listening on %s:%s",
            self.config.ae_title,
            self.config.bind_address,
            self.port,
        )

    def serve_forever(self) -> None:
        """待ち受けて戻らない（CLI の `mwl serve`）."""
        logger.info(
            "MWL SCP %s listening on %s:%s",
            self.config.ae_title,
            self.config.bind_address,
            self.config.port,
        )
        try:
            self.make_ae().start_server(
                (self.config.bind_address, self.config.port),
                block=True,
                evt_handlers=self.handlers,
            )
        except OSError as exc:
            raise MwlServerError(
                "MWL SCP could not listen",
                {"address": self.config.bind_address, "port": self.config.port, "error": str(exc)},
            ) from exc

    @property
    def port(self) -> int:
        """待ち受けているポート（設定の port が 0 のときは OS が選んだ番号）."""
        if self._server is None:
            return self.config.port
        return int(self._server.server_address[1])

    @property
    def running(self) -> bool:
        return self._server is not None

    def echo(self, timeout: float = ECHO_TIMEOUT_SECONDS) -> bool:
        """自分の待ち受けに、ループバックから C-ECHO を 1 回かけ、成功なら True.

        待ち受けが止まっているときは送らず False。画面の「接続確認」が使う
        （docs/spec/03_web_cli.md 3.1）。
        """
        if self._server is None:
            return False
        ae = AE(ae_title=ECHO_CALLING_AE_TITLE)
        ae.add_requested_context(Verification)
        ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = ae.connection_timeout = timeout
        assoc = ae.associate(
            _loopback_of(self.config.bind_address), self.port, ae_title=self.config.ae_title
        )
        if not assoc.is_established:
            return False
        try:
            status = assoc.send_c_echo()
        finally:
            assoc.release()
        return bool(status) and int(status.Status) == STATUS_SUCCESS

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    def _handle_n_create(self, event: Any) -> tuple[int | Dataset, Dataset | None]:
        try:
            return handle_n_create(
                self.store, event.request.AffectedSOPInstanceUID, event.attribute_list
            )
        except Exception:  # noqa: BLE001 - 相手には Processing Failure を返し、理由はログに残す
            logger.exception("MPPS N-CREATE failed")
            return STATUS_PROCESSING_FAILURE, None

    def _handle_n_set(self, event: Any) -> tuple[int | Dataset, Dataset | None]:
        try:
            return handle_n_set(
                self.store, event.request.RequestedSOPInstanceUID, event.modification_list
            )
        except Exception:  # noqa: BLE001 - 相手には Processing Failure を返し、理由はログに残す
            logger.exception("MPPS N-SET failed")
            return STATUS_PROCESSING_FAILURE, None

    def _handle_find(self, event: Any) -> Iterator[tuple[int, Dataset | None]]:
        requestor = event.assoc.requestor
        try:
            request = event.identifier
            status, responses = find_worklist(request, self.store, self.config)
        except Exception:  # noqa: BLE001 - 相手には Failure を返し、理由はログに残す
            logger.exception("C-FIND MWL failed")
            yield STATUS_UNABLE_TO_PROCESS, None
            return
        logger.info(
            "C-FIND MWL from %s@%s: %s match(es), status 0x%04X",
            requestor.ae_title,
            requestor.address,
            len(responses),
            status,
        )
        for pending, response in responses:
            if event.is_cancelled:
                yield STATUS_CANCEL, None
                return
            yield pending, response
        yield (STATUS_CANCEL if event.is_cancelled else status), None
