"""HL7 の受け手の試験用のスタブ（スレッドの TCP サーバー。接続のたびに 1 通を受けて ACK を返す）."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.hl7.mllp import END_BLOCK, START_BLOCK, frame

TIMEOUT = 2.0


@dataclass
class Receiver:
    port: int
    received: list[str] = field(default_factory=list)

    @property
    def types(self) -> list[str]:
        """受けたメッセージの MSH-9 の先頭 2 つ（例 ADT^A40）."""
        return ["^".join(_msh(text)[8].split("^")[:2]) for text in self.received]


def _msh(text: str) -> list[str]:
    return text.split("\r")[0].split("|")


def control_id(text: str) -> str:
    return _msh(text)[9]


def ack(code: str, text: str, message: str = "") -> bytes:
    """受けたメッセージ `text` への ACK（MSA-2 は受けた MSH-10）."""
    body = f"MSH|^~\\&|PACS|PACS|RIS_EMU|TEST_HOSPITAL|20261024201531||ACK|A1|P|2.3.1\rMSA|{code}|{control_id(text)}|{message}\r"
    return frame(body.encode("utf-8"))


Responder = Callable[[str], bytes | None]


@contextmanager
def stub_receiver(respond: Responder) -> Iterator[Receiver]:
    """接続を受け続け、枠を読んで `respond(本文)` の返すバイト列を返す。None なら何も返さず閉じる."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(0.2)
    receiver = Receiver(port=server.getsockname()[1])
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(TIMEOUT)
                buffer = b""
                try:
                    while END_BLOCK not in buffer:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk
                except OSError:
                    continue
                if END_BLOCK not in buffer:
                    continue
                text = buffer[len(START_BLOCK) : buffer.index(END_BLOCK)].decode("utf-8")
                receiver.received.append(text)
                reply = respond(text)
                if reply is not None:
                    try:
                        connection.sendall(reply)
                    except OSError:
                        continue

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield receiver
    finally:
        stop.set()
        server.close()
        thread.join(timeout=TIMEOUT * 3)
