import asyncio
from pathlib import Path
import uuid

import pytest

from old_sun_mcp.console_broker import (
    ConsoleBroker,
    ConsolePolicyStore,
    ConsoleTranscript,
    InputPriority,
)
from old_sun_mcp.errors import OldSunError


def test_transcript_keeps_absolute_cursors_across_compaction_and_restart(tmp_path: Path) -> None:
    transcript = ConsoleTranscript(tmp_path / "console.bin", capacity_bytes=8)

    assert transcript.append(b"abcdef") == (0, 6)
    assert transcript.append(b"ghijkl") == (6, 12)

    result = transcript.read(0, 20)
    assert result["gap"] is True
    assert result["base_cursor"] == 4
    assert result["next_cursor"] == 12
    assert result["data"] == b"efghijkl"

    restarted = ConsoleTranscript(tmp_path / "console.bin", capacity_bytes=8)
    assert restarted.cursor == 12
    assert restarted.read(8, 4)["data"] == b"ijkl"


def test_policy_defaults_open_persists_and_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    store = ConsolePolicyStore(path)

    assert store.load().mcp_write_enabled is True
    saved = store.set_mcp_write_enabled(False, actor_id=42, actor_login="ryancnelson")
    assert saved.mcp_write_enabled is False
    assert ConsolePolicyStore(path).load().updated_by_id == 42

    path.write_text("not json", encoding="utf-8")
    broken = ConsolePolicyStore(path).load()
    assert broken.mcp_write_enabled is False
    assert broken.error is not None


@pytest.mark.asyncio
async def test_broker_reads_fake_console_and_reconnects(tmp_path: Path) -> None:
    socket_path = Path("/tmp") / f"old-sun-console-{uuid.uuid4().hex[:12]}.sock"
    first_connected = asyncio.Event()
    second_connected = asyncio.Event()
    connections = 0

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connections
        connections += 1
        if connections == 1:
            first_connected.set()
            writer.write(b"ok ")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        else:
            second_connected.set()
            writer.write(b"again")
            await writer.drain()
            await asyncio.sleep(1)
            writer.close()

    server = await asyncio.start_unix_server(accept, path=socket_path)
    broker = ConsoleBroker(
        console_socket=socket_path,
        transcript=ConsoleTranscript(tmp_path / "transcript.bin", capacity_bytes=100),
        policy_store=ConsolePolicyStore(tmp_path / "policy.json"),
        reconnect_seconds=0.01,
    )
    await broker.start()
    try:
        await asyncio.wait_for(first_connected.wait(), 1)
        await asyncio.wait_for(second_connected.wait(), 1)
        result = await broker.expect(b"again", after_cursor=0, timeout_seconds=1)
        assert result["matched"] is True
        assert broker.read(0, 100)["data"] == b"ok again"
    finally:
        await broker.stop()
        server.close()
        await server.wait_closed()
        socket_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_human_input_precedes_queued_mcp_input(tmp_path: Path) -> None:
    broker = ConsoleBroker(
        console_socket=tmp_path / "missing.sock",
        transcript=ConsoleTranscript(tmp_path / "transcript.bin", capacity_bytes=100),
        policy_store=ConsolePolicyStore(tmp_path / "policy.json"),
    )

    await broker._input_queue.put(InputPriority.MCP, b"mcp", "mcp")
    await broker._input_queue.put(InputPriority.HUMAN, b"\x03", "human")

    first = await broker._input_queue.get()
    second = await broker._input_queue.get()
    assert first.data == b"\x03"
    assert second.data == b"mcp"


@pytest.mark.asyncio
async def test_policy_blocks_mcp_but_not_human_input(tmp_path: Path) -> None:
    store = ConsolePolicyStore(tmp_path / "policy.json")
    broker = ConsoleBroker(
        console_socket=tmp_path / "missing.sock",
        transcript=ConsoleTranscript(tmp_path / "transcript.bin", capacity_bytes=100),
        policy_store=store,
    )
    lease = await broker.acquire("codex", "test", ttl_seconds=30)
    store.set_mcp_write_enabled(False, actor_id=42, actor_login="ryancnelson")

    with pytest.raises(OldSunError) as raised:
        await broker.queue_mcp_input(lease["lease_id"], b"date\r", "test")
    assert raised.value.code == "CONSOLE_POLICY_BLOCKED"

    await broker.queue_human_input(b"\x03")
    queued = await broker._input_queue.get()
    assert queued.source == "human"


@pytest.mark.asyncio
async def test_lease_is_exclusive_expiring_and_releasable(tmp_path: Path) -> None:
    broker = ConsoleBroker(
        console_socket=tmp_path / "missing.sock",
        transcript=ConsoleTranscript(tmp_path / "transcript.bin", capacity_bytes=100),
        policy_store=ConsolePolicyStore(tmp_path / "policy.json"),
    )
    lease = await broker.acquire("codex", "test", ttl_seconds=0.01)

    with pytest.raises(OldSunError) as raised:
        await broker.acquire("other", "test", ttl_seconds=10)
    assert raised.value.code == "CONSOLE_LEASE_HELD"

    await asyncio.sleep(0.02)
    replacement = await broker.acquire("other", "test", ttl_seconds=10)
    assert replacement["lease_id"] != lease["lease_id"]
    assert await broker.release(replacement["lease_id"]) is True
    assert await broker.release(replacement["lease_id"]) is False
