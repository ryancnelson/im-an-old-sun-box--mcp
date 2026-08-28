import json
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from old_sun_mcp.console_client import control_request
from old_sun_mcp.errors import OldSunError


def serve_once(path: Path, response: dict) -> threading.Thread:
    ready = threading.Event()

    def run() -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen(1)
        ready.set()
        connection, _ = server.accept()
        with connection:
            assert json.loads(connection.recv(4096))["token"] == "token"
            connection.sendall((json.dumps(response) + "\n").encode())
        server.close()

    thread = threading.Thread(target=run)
    thread.start()
    assert ready.wait(1)
    return thread


def test_control_client_returns_state() -> None:
    with tempfile.TemporaryDirectory(prefix="osc-", dir="/tmp") as directory:
        path = Path(directory) / "control.sock"
        thread = serve_once(path, {"ok": True, "connected": True, "mcp_write_blocked": False})
        response = control_request(str(path), "token", {"operation": "status"}, timeout_seconds=1, max_bytes=4096)
        thread.join(1)
    assert response == {"connected": True, "mcp_write_blocked": False}


def test_control_client_maps_write_block_to_typed_error() -> None:
    with tempfile.TemporaryDirectory(prefix="osc-", dir="/tmp") as directory:
        path = Path(directory) / "control.sock"
        thread = serve_once(path, {"ok": False, "error": "write_blocked", "mcp_write_blocked": True})
        with pytest.raises(OldSunError) as caught:
            control_request(str(path), "token", {"operation": "write"}, timeout_seconds=1, max_bytes=4096)
        thread.join(1)
    assert caught.value.code == "CONSOLE_WRITE_BLOCKED"
    assert caught.value.details["mcp_write_blocked"] is True
