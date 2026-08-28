import asyncio
import tempfile
from pathlib import Path

import pytest

from old_sun_mcp.console_broker import BoundedHistory, ConsoleBroker, McpWriteBlocked
from old_sun_mcp.console_state import OperatorState


def test_bounded_history_retains_only_tail() -> None:
    history = BoundedHistory(5)
    history.append(b"abc")
    history.append(b"defg")
    assert history.bytes() == b"cdefg"


@pytest.mark.asyncio
async def test_broker_reads_reconnects_and_enforces_actor_policy(tmp_path) -> None:
    socket_dir = tempfile.TemporaryDirectory(prefix="osc-", dir="/tmp")
    socket_path = Path(socket_dir.name) / "console.sock"
    received = bytearray()
    connected = asyncio.Event()

    async def qemu(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connected.set()
        writer.write(b"booting\r\n")
        await writer.drain()
        received.extend(await reader.read(32))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(qemu, path=str(socket_path))
    state = OperatorState(tmp_path / "state.json")
    broker = ConsoleBroker(socket_path, state, retry_seconds=0.02)
    await broker.start()
    await asyncio.wait_for(connected.wait(), 1)
    for _ in range(100):
        if broker.history.bytes() == b"booting\r\n":
            break
        await asyncio.sleep(0.01)

    with pytest.raises(McpWriteBlocked):
        await broker.write_mcp(b"mcp\r")
    await broker.write_human(b"human\r")
    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.01)
    assert received == b"human\r"

    await broker.set_mcp_write_blocked(False)
    assert state.mcp_write_blocked is False
    await broker.stop()
    server.close()
    await server.wait_closed()
    socket_dir.cleanup()
