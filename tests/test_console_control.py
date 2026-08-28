import asyncio
import base64
import json
import tempfile
from pathlib import Path

import pytest

from old_sun_mcp.console_broker import ConsoleBroker
from old_sun_mcp.console_control import ConsoleControlServer
from old_sun_mcp.console_state import OperatorState


async def request(path, payload):
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    response = json.loads(await reader.readline())
    writer.close()
    await writer.wait_closed()
    return response


@pytest.mark.asyncio
async def test_control_socket_authenticates_and_reports_blocked_write(tmp_path) -> None:
    socket_dir = tempfile.TemporaryDirectory(prefix="osc-", dir="/tmp")
    state = OperatorState(tmp_path / "state.json")
    state.load()
    broker = ConsoleBroker(tmp_path / "missing-console.sock", state)
    broker.history.append(b"hello")
    control = ConsoleControlServer(Path(socket_dir.name) / "control.sock", "correct-token", broker)
    await control.start()
    try:
        denied = await request(control.path, {"token": "wrong", "operation": "status"})
        assert denied["error"] == "unauthorized"

        status = await request(control.path, {"token": "correct-token", "operation": "status"})
        assert status["ok"] is True
        assert status["mcp_write_blocked"] is True

        read = await request(control.path, {"token": "correct-token", "operation": "read"})
        assert base64.b64decode(read["data_base64"]) == b"hello"

        blocked = await request(
            control.path,
            {
                "token": "correct-token",
                "operation": "write",
                "reason": "interrupt a guest command",
                "data_base64": base64.b64encode(b"\x03").decode(),
            },
        )
        assert blocked["error"] == "write_blocked"
        assert blocked["mcp_write_blocked"] is True
    finally:
        await control.stop()
        socket_dir.cleanup()
