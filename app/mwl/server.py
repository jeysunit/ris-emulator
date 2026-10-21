"""MWL の SCP（pynetdicom。ADR-0001、spec/02_mwl_scp.md）.

C-FIND（Modality Worklist Information Model - FIND、1.2.840.10008.5.1.4.31）と
C-ECHO（Verification）を受ける。予約は要求のたびに保存先から読み直す。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification

from app.core.exceptions import MwlServerError
from app.core.matching import has_matching_keys, matches
from app.core.mwl_dataset import build_response, has_unsupported_keys, order_to_dataset
from app.services.config import MwlConfig
from app.services.store import OrderStore

logger = logging.getLogger(__name__)

STATUS_PENDING = 0xFF00
STATUS_PENDING_WARNING = 0xFF01
STATUS_SUCCESS = 0x0000
STATUS_CANCEL = 0xFE00
STATUS_OUT_OF_RESOURCES = 0xA700
STATUS_UNABLE_TO_PROCESS = 0xC001


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
        ae.add_supported_context(Verification)
        return ae

    @property
    def handlers(self) -> list[tuple[Any, Any]]:
        return [(evt.EVT_C_FIND, self._handle_find)]

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

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None

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
