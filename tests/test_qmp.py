import json
from pathlib import Path
import socket
import threading
import uuid

import pytest

from old_sun_mcp.errors import OldSunError
from old_sun_mcp.qmp import qmp_request


def fake_qmp(path: Path, result: object) -> threading.Thread:
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path)); server.listen(1); ready.set()
            connection, _ = server.accept()
            with connection, connection.makefile("rwb", buffering=0) as stream:
                stream.write(json.dumps({"QMP": {"version": {}}}).encode() + b"\n")
                capabilities = json.loads(stream.readline())
                stream.write(json.dumps({"return": {}, "id": capabilities["id"]}).encode() + b"\n")
                request = json.loads(stream.readline())
                stream.write(json.dumps({"return": result, "id": request["id"]}).encode() + b"\n")

    thread = threading.Thread(target=serve, daemon=True); thread.start(); ready.wait(1)
    return thread


def test_qmp_negotiates_and_returns_typed_status() -> None:
    path = Path("/tmp") / f"old-sun-qmp-{uuid.uuid4().hex[:10]}.sock"
    try:
        thread = fake_qmp(path, {"status": "running", "running": True})
        result = qmp_request(path, "query-status", 1, 1000)
        thread.join(1)
        assert result == {"status": "running", "running": True}
    finally:
        path.unlink(missing_ok=True)


def test_qmp_missing_socket_is_typed(tmp_path: Path) -> None:
    with pytest.raises(OldSunError) as raised:
        qmp_request(tmp_path / "missing.sock", "query-status", 0.1, 100)
    assert raised.value.code == "SOCKET_CONNECT_FAILED"
