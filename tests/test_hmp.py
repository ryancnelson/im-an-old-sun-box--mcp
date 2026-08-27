import socket
import threading
import time
from pathlib import Path
import uuid

import pytest

from old_sun_mcp.errors import OldSunError
from old_sun_mcp.hmp import classify_control, hmp_request, validate_query


def fake_hmp(path: Path, response: bytes | None = b"VM status: running\r\n(qemu) ") -> threading.Thread:
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path)); server.listen(1); ready.set()
            connection, _ = server.accept()
            with connection:
                connection.sendall(b"QEMU monitor\r\n(qemu) ")
                connection.recv(4096)
                if response is None:
                    time.sleep(0.2)
                else:
                    connection.sendall(response)

    thread = threading.Thread(target=serve, daemon=True); thread.start(); ready.wait(1)
    return thread


def test_hmp_request_frames_prompt(tmp_path: Path) -> None:
    # macOS limits AF_UNIX paths to 104 bytes; pytest's temp path can exceed it.
    path = Path("/tmp") / f"old-sun-{uuid.uuid4().hex[:12]}.sock"
    try:
        thread = fake_hmp(path)
        result = hmp_request(path, "info status", 1, 1000)
        thread.join(1)
        assert "VM status: running" in result["response"]
    finally:
        path.unlink(missing_ok=True)


def test_hmp_query_and_control_allowlists() -> None:
    assert validate_query("info status") == "info status"
    with pytest.raises(OldSunError): validate_query("stop")
    assert classify_control("stop") == "reversible"
    assert classify_control("system_reset") == "disruptive"
    with pytest.raises(OldSunError): classify_control("quit")


def test_missing_socket_is_typed(tmp_path: Path) -> None:
    with pytest.raises(OldSunError) as raised:
        hmp_request(tmp_path / "missing.sock", "info status", 0.1, 100)
    assert raised.value.code == "SOCKET_CONNECT_FAILED"


def test_monitor_timeout_is_typed() -> None:
    path = Path("/tmp") / f"old-sun-{uuid.uuid4().hex[:12]}.sock"
    thread = fake_hmp(path, response=None)
    try:
        with pytest.raises(OldSunError) as raised:
            hmp_request(path, "info status", 0.05, 100)
        assert raised.value.code == "SOCKET_TIMEOUT"
    finally:
        thread.join(1); path.unlink(missing_ok=True)
