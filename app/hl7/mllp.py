"""MLLP での HL7 メッセージの送信と ACK の受け取り（docs/spec/06_hl7_pir.md 4 章）.

枠は HL7 Implementation Guide 付録 C の Minimal Lower Layer Protocol：
`<VT>` 本文 `<FS><CR>`（VT=0x0B、FS=0x1C、CR=0x0D）。IHE RAD TF-2 2.4.1.1 が使うよう求めている。
送り手が接続を開き、1 通を送って ACK を 1 通受け取り、接続を閉じる。
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Literal

from app.core.exceptions import AckParseError
from app.core.hl7 import Hl7Message, parse_ack

START_BLOCK = b"\x0b"
END_BLOCK = b"\x1c\x0d"
# 開発用の相手の ACK は数百バイト。暴走した相手にメモリを使わないための上限
MAX_ACK_BYTES = 1_048_576
_RECEIVE_SIZE = 4096

Outcome = Literal["accepted", "rejected", "failed"]


@dataclass(frozen=True)
class DeliveryResult:
    """送信の結果。`accepted` は AA、`rejected` は AE・AR、`failed` はそれ以外（接続・枠・ACK の誤り）."""

    outcome: Outcome
    ack_code: str = ""
    ack_text: str = ""
    detail: str = ""


def frame(payload: bytes) -> bytes:
    return START_BLOCK + payload + END_BLOCK


def send_message(message: Hl7Message, host: str, port: int, timeout: float) -> DeliveryResult:
    """MLLP で 1 通を送り、ACK の MSA-1 で結果を分ける.

    接続できない・時間切れ・枠が壊れている・ACK を読めない・MSA-2 が送ったメッセージの
    MSH-10 と違う・AA AE AR 以外の確認コードは、例外にせず `failed` で返す。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(frame(message.to_bytes()))
            raw = _receive_frame(connection)
    except OSError as exc:
        return DeliveryResult("failed", detail=f"{host}:{port} と通信できません：{exc}")
    except _FrameError as exc:
        return DeliveryResult("failed", detail=str(exc))
    try:
        ack = parse_ack(raw)
    except AckParseError as exc:
        return DeliveryResult("failed", detail=str(exc))
    if ack.control_id != message.control_id:
        return DeliveryResult(
            "failed",
            ack.code,
            ack.text,
            f"ACK の MSA-2（{ack.control_id}）が送った MSH-10（{message.control_id}）と違います",
        )
    if ack.code == "AA":
        return DeliveryResult("accepted", ack.code, ack.text)
    if ack.code in ("AE", "AR"):
        detail = ack.error or ack.text
        return DeliveryResult("rejected", ack.code, ack.text, detail)
    return DeliveryResult("failed", ack.code, ack.text, f"想定外の確認コードです：{ack.code or '（空）'}")


class _FrameError(Exception):
    """MLLP の枠が壊れている."""


def _receive_frame(connection: socket.socket) -> bytes:
    """`<VT>` で始まり `<FS><CR>` で終わる 1 通を受け取り、枠を外した本文を返す."""
    buffer = b""
    while END_BLOCK not in buffer:
        if len(buffer) > MAX_ACK_BYTES:
            raise _FrameError("ACK が大きすぎます")
        chunk = connection.recv(_RECEIVE_SIZE)
        if not chunk:
            raise _FrameError("ACK の枠が終わる前に、相手が接続を閉じました")
        buffer += chunk
    if not buffer.startswith(START_BLOCK):
        raise _FrameError("ACK が MLLP の開始（0x0B）で始まっていません")
    return buffer[len(START_BLOCK) : buffer.index(END_BLOCK)]
