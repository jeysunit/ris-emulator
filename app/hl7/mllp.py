"""MLLP での HL7 メッセージの送信と ACK の受け取り（docs/spec/06_hl7_pir.md 4 章）.

枠は HL7 Implementation Guide 付録 C の Minimal Lower Layer Protocol：
`<VT>` 本文 `<FS><CR>`（VT=0x0B、FS=0x1C、CR=0x0D）。IHE RAD TF-2 2.4.1.1 が使うよう求めている。
送り手が接続を開き、1 通を送って ACK を 1 通受け取り、接続を閉じる。
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import Literal

from app.core.exceptions import AckParseError
from app.core.hl7 import Hl7Message, parse_ack, visible

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


# 接続確認の失敗の理由の 1 句（部品集の接続先の表。AEタイトルは MLLP に無いので 3 つ）
REASON_NO_RESPONSE = "応答がありません"
REASON_REFUSED = "接続を断られました"
REASON_UNKNOWN_HOST = "ホスト名を引けません"


@dataclass(frozen=True)
class ConnectionCheck:
    """接続確認の結果。`reason` は失敗の理由の 1 句、`detail` は記録に残す元の文."""

    ok: bool
    reason: str = ""
    detail: str = ""


def _resolve(host: str, port: int, timeout: float) -> list[str]:
    """名前を引いて、アドレスを引けた順に返す。`timeout` 秒で引けなければ TimeoutError.

    getaddrinfo には時間の上限を渡せない（create_connection の timeout は接続にしか
    効かない）ので、別のスレッドで引き、待つ時間に上限を付ける。引き終わらなかった
    スレッドは、OS の名前解決が諦めた時点で自然に終わる（デーモンなので終了を止めない）。
    """
    outcome: dict[str, object] = {}

    def work() -> None:
        try:
            outcome["infos"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError) as exc:  # UnicodeError：ホスト名が IDNA に直せない
            outcome["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"名前の解決が {timeout:g} 秒で終わりませんでした")
    error = outcome.get("error")
    if isinstance(error, BaseException):
        raise error
    infos: list[tuple] = outcome["infos"]  # type: ignore[assignment]
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


def check_connection(host: str, port: int, timeout: float) -> ConnectionCheck:
    """MLLP の接続を開けるかだけを確かめる。何も送らず、すぐ閉じる.

    HL7 v2 の MLLP は、接続を開いて 1 通送り、ACK を受けて閉じる（上の docstring）ので、
    相手の受け口が待ち受けているかは、接続を開けるかで分かる。メッセージは送らない
    （接続を開いて閉じるので、受け手によっては接続のログが残る）。名前の解決と接続を合わせて `timeout` 秒までで返す
    （IPv4・IPv6 の両方に解けるときも倍にならない）。
    """
    deadline = time.monotonic() + timeout
    try:
        addresses = _resolve(host, port, timeout)
    except (OSError, UnicodeError) as exc:  # TimeoutError（引き終わらない）を含む
        return ConnectionCheck(False, REASON_UNKNOWN_HOST, str(exc))
    if not addresses:
        return ConnectionCheck(False, REASON_UNKNOWN_HOST, "アドレスがありません")
    failure = ConnectionCheck(False, REASON_NO_RESPONSE, "時間切れ")
    for address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with socket.create_connection((address, port), timeout=remaining):
                return ConnectionCheck(True)
        except ConnectionRefusedError as exc:
            failure = ConnectionCheck(False, REASON_REFUSED, str(exc))
        except OSError as exc:  # 時間切れ・到達できない経路など
            failure = ConnectionCheck(False, REASON_NO_RESPONSE, str(exc))
    return failure


def send_message(message: Hl7Message, host: str, port: int, timeout: float) -> DeliveryResult:
    """MLLP で 1 通を送り、ACK の MSA-1 で結果を分ける.

    接続できない・時間切れ・枠が壊れている・ACK を読めない・MSA-2 が送ったメッセージの
    MSH-10 と違う・AA AE AR 以外の確認コードは、例外にせず `failed` で返す。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(frame(message.to_bytes()))
            raw = _receive_frame(connection, timeout)
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
            f"ACK の MSA-2（{visible(ack.control_id)}）が送った MSH-10"
            f"（{visible(message.control_id)}）と違います",
        )
    if ack.code == "AA":
        return DeliveryResult("accepted", ack.code, ack.text)
    if ack.code in ("AE", "AR"):
        detail = ack.error or ack.text
        return DeliveryResult("rejected", ack.code, ack.text, detail)
    return DeliveryResult("failed", ack.code, ack.text, f"想定外の確認コードです：{ack.code or '（空）'}")


class _FrameError(Exception):
    """MLLP の枠が壊れている."""


def _receive_frame(connection: socket.socket, timeout: float) -> bytes:
    """`<VT>` で始まり `<FS><CR>` で終わる 1 通を受け取り、枠を外した本文を返す.

    `timeout` は ACK を受け取り終えるまでの全体の秒数。少しずつ返す相手でも超えたら失敗にする。
    """
    deadline = time.monotonic() + timeout
    buffer = b""
    while END_BLOCK not in buffer:
        # 本文の上限に、開始と終端の分を足す（終端が 2 回の受信に分かれても、上限ちょうどは通す）
        if len(buffer) > MAX_ACK_BYTES + len(START_BLOCK) + len(END_BLOCK):
            raise _FrameError("ACK が大きすぎます")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ACK を待つ時間が過ぎました")
        connection.settimeout(remaining)
        chunk = connection.recv(_RECEIVE_SIZE)
        if not chunk:
            raise _FrameError("ACK の枠が終わる前に、相手が接続を閉じました")
        buffer += chunk
    if not buffer.startswith(START_BLOCK):
        raise _FrameError("ACK が MLLP の開始（0x0B）で始まっていません")
    body = buffer[len(START_BLOCK) : buffer.index(END_BLOCK)]
    if len(body) > MAX_ACK_BYTES:
        raise _FrameError("ACK が大きすぎます")
    return body
