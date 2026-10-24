"""MLLP の送信と ACK の扱いの試験。受け手は試験用のスタブ（スレッドの TCP サーバー）."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from app.core.hl7 import Hl7Header, Hl7Message, build_adt_a40
from app.core.models import Patient, PersonName
from app.hl7.mllp import END_BLOCK, MAX_ACK_BYTES, START_BLOCK, frame, send_message

NOW = datetime(2026, 10, 24, 20, 15, 30)
HEADER = Hl7Header("RIS_EMU", "TEST_HOSPITAL", "PACS", "PACS")
PATIENT = Patient(patient_id="RE0000001", name=PersonName(alphabetic="YAMADA^TARO", ideographic="山田^太郎"))
TIMEOUT = 2.0


def _message() -> Hl7Message:
    return build_adt_a40(
        HEADER, PATIENT, namespace="RIS_EMU", prior_patient_id="ER0001", now=NOW, control_id="CTRL1"
    )


def _ack(code: str, control_id: str = "CTRL1", text: str = "", err: str = "") -> bytes:
    body = f"MSH|^~\\&|PACS|PACS|RIS_EMU|TEST_HOSPITAL|20261024201531||ACK|A1|P|2.3.1\rMSA|{code}|{control_id}|{text}\r"
    if err:
        body += f"ERR|{err}\r"
    return frame(body.encode("utf-8"))


@dataclass
class Receiver:
    port: int
    received: list[bytes] = field(default_factory=list)


@contextmanager
def stub_receiver(respond: Callable[[bytes], bytes | None]) -> Iterator[Receiver]:
    """1 回の接続を受け、枠を読んで `respond(本文)` の返すバイト列を返す。None なら何も返さず閉じる."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(TIMEOUT * 2)
    receiver = Receiver(port=server.getsockname()[1])

    def serve() -> None:
        try:
            connection, _ = server.accept()
        except OSError:
            return
        with connection:
            connection.settimeout(TIMEOUT)
            buffer = b""
            try:
                while END_BLOCK not in buffer:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return
                    buffer += chunk
            except OSError:
                return
            assert buffer.startswith(START_BLOCK)
            body = buffer[len(START_BLOCK) : buffer.index(END_BLOCK)]
            receiver.received.append(body)
            reply = respond(body)
            if reply is not None:
                try:
                    connection.sendall(reply)
                except OSError:  # 送り手が先に閉じた（大きすぎる ACK の試験）
                    return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield receiver
    finally:
        server.close()
        thread.join(timeout=TIMEOUT * 3)


def test_frame_wraps_with_vt_and_fs_cr() -> None:
    assert frame(b"MSH|x") == b"\x0bMSH|x\x1c\r"


def test_accepted_on_aa_and_message_arrives_whole() -> None:
    message = _message()
    with stub_receiver(lambda _: _ack("AA")) as receiver:
        result = send_message(message, "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "accepted" and result.ack_code == "AA"
    assert receiver.received == [message.to_bytes()]
    assert "山田^太郎".encode() in receiver.received[0]


@pytest.mark.parametrize("code", ["AE", "AR"])
def test_rejected_on_ae_and_ar(code: str) -> None:
    with stub_receiver(lambda _: _ack(code, text="patient not found", err="PID^1^3")) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "rejected" and result.ack_code == code
    assert result.ack_text == "patient not found" and result.detail == "PID^1^3"


def test_rejected_without_err_uses_msa_text() -> None:
    with stub_receiver(lambda _: _ack("AR", text="bad message")) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "rejected" and result.detail == "bad message"


def test_ack_for_another_message_is_a_failure() -> None:
    with stub_receiver(lambda _: _ack("AA", control_id="OTHER")) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "MSA-2" in result.detail


@pytest.mark.parametrize("code", ["CA", "CE", "CR", "XX", ""])
def test_unexpected_ack_code_is_a_failure(code: str) -> None:
    with stub_receiver(lambda _: _ack(code)) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "確認コード" in result.detail


def test_connection_refused_is_a_failure() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = send_message(_message(), "127.0.0.1", port, TIMEOUT)
    assert result.outcome == "failed" and f"127.0.0.1:{port}" in result.detail


def test_receiver_closing_without_ack_is_a_failure() -> None:
    with stub_receiver(lambda _: None) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "接続を閉じました" in result.detail


def test_ack_without_start_block_is_a_failure() -> None:
    with stub_receiver(lambda _: _ack("AA")[1:]) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "0x0B" in result.detail


def test_unparsable_ack_is_a_failure() -> None:
    with stub_receiver(lambda _: frame(b"hello")) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "MSH" in result.detail


def test_silent_receiver_times_out() -> None:
    release = threading.Event()

    def hold(_: bytes) -> bytes | None:
        release.wait(TIMEOUT * 2)
        return None

    with stub_receiver(hold) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, 0.3)
        release.set()
    assert result.outcome == "failed" and "通信できません" in result.detail


def test_slowly_dripping_ack_hits_the_overall_deadline() -> None:
    """各 recv の待ちは短くても、ACK を受け終えるまでの全体で timeout を超えたら失敗にする."""
    release = threading.Event()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(START_BLOCK)
            while not release.is_set():
                try:
                    connection.sendall(b"x")
                except OSError:
                    return
                release.wait(0.05)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    started = time.monotonic()
    result = send_message(_message(), "127.0.0.1", port, 0.5)
    elapsed = time.monotonic() - started
    release.set()
    server.close()
    thread.join(timeout=TIMEOUT)
    assert result.outcome == "failed" and "通信できません" in result.detail
    assert elapsed < 1.5


def _ack_of_body_size(size: int) -> bytes:
    head = "MSH|^~\\&|PACS|PACS|RIS_EMU|X|20261024||ACK|A1|P|2.3.1\rMSA|AA|CTRL1|"
    return (head + "x" * (size - len(head) - 1) + "\r").encode("ascii")


@pytest.mark.parametrize("split_terminator", [False, True])
def test_ack_of_exactly_the_limit_is_accepted(split_terminator: bool) -> None:
    """本文が上限ちょうどなら、終端が同じ受信でも別の受信（FS と CR の間）でも受理する."""
    body = _ack_of_body_size(MAX_ACK_BYTES)
    assert len(body) == MAX_ACK_BYTES

    if not split_terminator:
        with stub_receiver(lambda _: START_BLOCK + body + END_BLOCK) as receiver:
            result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    else:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)

        def serve() -> None:
            connection, _ = server.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(START_BLOCK + body + END_BLOCK[:1])
                time.sleep(0.2)
                connection.sendall(END_BLOCK[1:])

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = send_message(_message(), "127.0.0.1", server.getsockname()[1], TIMEOUT)
        thread.join(timeout=TIMEOUT)
        server.close()
    assert result.outcome == "accepted"


def test_one_byte_over_the_limit_is_a_failure() -> None:
    body = _ack_of_body_size(MAX_ACK_BYTES + 1)
    with stub_receiver(lambda _: START_BLOCK + body + END_BLOCK) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "大きすぎます" in result.detail


def test_ack_matches_a_control_id_with_format_characters() -> None:
    """MSA-2 の照合は生の値で行う。表示用の変換が入った値で比べない."""
    control_id = "A​B"
    message = build_adt_a40(
        HEADER, PATIENT, namespace="RIS_EMU", prior_patient_id="ER0001", now=NOW, control_id=control_id
    )
    with stub_receiver(lambda _: _ack("AA", control_id=control_id)) as receiver:
        result = send_message(message, "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "accepted"


def test_complete_oversized_ack_is_a_failure() -> None:
    """上限を超える本文が、終端を含む 1 回の受信で届いても失敗にする."""
    oversized = START_BLOCK + b"x" * (MAX_ACK_BYTES + 10) + END_BLOCK
    with stub_receiver(lambda _: oversized) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed" and "大きすぎます" in result.detail


def test_oversized_ack_is_a_failure() -> None:
    with stub_receiver(lambda _: START_BLOCK + b"x" * (MAX_ACK_BYTES + 10000)) as receiver:
        result = send_message(_message(), "127.0.0.1", receiver.port, TIMEOUT)
    assert result.outcome == "failed"
