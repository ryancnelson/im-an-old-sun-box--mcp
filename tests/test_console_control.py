import asyncio
import base64
import json
import tempfile
from pathlib import Path

import pytest

from old_sun_mcp.console_broker import ConsoleBroker
from old_sun_mcp.console_control import ConsoleControlServer
from old_sun_mcp.console_state import OperatorState


class FakeTargetManager:
    def __init__(self, state: OperatorState):
        self.state = state
        self.current = None

    async def discover(self):
        from old_sun_mcp.console_discovery import DiscoveryError, DiscoveryReport
        return DiscoveryReport((), {"ec2trib": DiscoveryError("timeout", "timed out")})

    async def select(self, target_id: str, *, actor: str = "human"):
        from old_sun_mcp.console_broker import McpWriteBlocked
        if self.state.mcp_write_blocked:
            raise McpWriteBlocked("blocked")
        if target_id == "missing":
            raise ValueError("unknown or stale console target; refresh discovery")
        raise ValueError("stale console target")

    def snapshot(self):
        return None

    def lifecycle_adapter(self):
        return ("/should/not/run",)


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


@pytest.mark.asyncio
async def test_control_target_reads_work_while_blocked_and_mutations_do_not(tmp_path) -> None:
    socket_dir = tempfile.TemporaryDirectory(prefix="osc-target-", dir="/tmp")
    state = OperatorState(tmp_path / "state.json")
    state.load()
    broker = ConsoleBroker(tmp_path / "missing-console.sock", state)
    manager = FakeTargetManager(state)
    control = ConsoleControlServer(
        Path(socket_dir.name) / "control.sock",
        "correct-token",
        broker,
        target_manager=manager,
    )
    await control.start()
    try:
        listing = await request(control.path, {"token": "correct-token", "operation": "list_targets"})
        assert listing["ok"] is True
        assert listing["errors"]["ec2trib"]["kind"] == "timeout"
        current = await request(control.path, {"token": "correct-token", "operation": "current_target"})
        assert current["current_target"] is None
        invalid = await request(
            control.path,
            {"token": "correct-token", "operation": "select_target", "target_id": "anything", "reason": ""},
        )
        assert invalid["error"] == "invalid_argument"
        blocked = await request(
            control.path,
            {"token": "correct-token", "operation": "select_target", "target_id": "anything", "reason": "debug it"},
        )
        assert blocked["error"] == "write_blocked"
        vm_blocked = await request(
            control.path,
            {"token": "correct-token", "operation": "vm_control", "action": "reset", "reason": "recover"},
        )
        assert vm_blocked["error"] == "write_blocked"
    finally:
        await control.stop()
        socket_dir.cleanup()
