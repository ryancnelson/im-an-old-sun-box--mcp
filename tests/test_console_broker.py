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
    history.clear()
    assert history.bytes() == b""


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


@pytest.mark.asyncio
async def test_broker_replaces_transport_without_losing_subscribers(tmp_path) -> None:
    socket_dir = tempfile.TemporaryDirectory(prefix="osc-switch-", dir="/tmp")
    first_path = Path(socket_dir.name) / "first.sock"
    second_path = Path(socket_dir.name) / "second.sock"

    async def first(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"first")
        await writer.drain()
        await reader.read()

    async def second(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"second")
        await writer.drain()
        await reader.read()

    first_server = await asyncio.start_unix_server(first, path=str(first_path))
    second_server = await asyncio.start_unix_server(second, path=str(second_path))
    broker = ConsoleBroker(first_path, OperatorState(tmp_path / "state.json"), retry_seconds=0.01)
    queue = broker.subscribe()
    await broker.start()
    for _ in range(100):
        if broker.history.bytes() == b"first":
            break
        await asyncio.sleep(0.01)

    await broker.replace_transport(second_path)
    for _ in range(100):
        if broker.history.bytes() == b"second":
            break
        await asyncio.sleep(0.01)

    assert broker.history.bytes() == b"second"
    statuses = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.kind == "status":
            statuses.append(event.connected)
    assert False in statuses
    assert statuses[-1] is True

    await broker.stop()
    first_server.close()
    second_server.close()
    await first_server.wait_closed()
    await second_server.wait_closed()
    socket_dir.cleanup()
