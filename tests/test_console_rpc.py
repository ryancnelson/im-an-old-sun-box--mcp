import asyncio
import base64
from pathlib import Path
import socket
import uuid

import pytest

from old_sun_mcp.console_broker import ConsoleBroker, ConsolePolicyStore, ConsoleTranscript
from old_sun_mcp.console_rpc import ConsoleRpcClient, ConsoleRpcServer
from old_sun_mcp.errors import OldSunError


def short_socket(name: str) -> Path:
    return Path("/tmp") / f"old-sun-{name}-{uuid.uuid4().hex[:10]}.sock"


@pytest.mark.asyncio
async def test_rpc_auth_status_lease_write_read_expect_and_release(tmp_path: Path) -> None:
    console_socket = short_socket("console")
    rpc_socket = short_socket("rpc")
    received = bytearray()
    keep_open = asyncio.Event()

    async def fake_console(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"ok ")
        await writer.drain()
        received.extend(await reader.readexactly(5))
        writer.write(b"help response")
        await writer.drain()
        await keep_open.wait()

    console_server = await asyncio.start_unix_server(fake_console, path=console_socket)
    broker = ConsoleBroker(
        console_socket=console_socket,
        transcript=ConsoleTranscript(tmp_path / "transcript.bin"),
        policy_store=ConsolePolicyStore(tmp_path / "policy.json"),
        reconnect_seconds=0.01,
        run_id="demo",
    )
    rpc_server = ConsoleRpcServer(rpc_socket, "correct-token", broker)
    await broker.start()
    await rpc_server.start()
    client = ConsoleRpcClient(rpc_socket, "correct-token", timeout_seconds=1)
    try:
        for _ in range(100):
            status = await asyncio.to_thread(client.request, "status")
            if status["console_connected"]:
                break
            await asyncio.sleep(0.01)
        assert status["run"] == "demo"

        lease = await asyncio.to_thread(
            client.request,
            "acquire",
            {"owner": "codex", "reason": "probe OBP", "ttl_seconds": 30},
        )
        written = await asyncio.to_thread(
            client.request,
            "write",
            {
                "lease_id": lease["lease_id"],
                "data_base64": base64.b64encode(b"help\r").decode("ascii"),
                "reason": "probe OBP",
            },
        )
        assert written["queued"] == 5

        expected = await asyncio.to_thread(
            client.request,
            "expect",
            {"pattern": "help response", "after_cursor": 0, "timeout_seconds": 1},
        )
        assert expected["matched"] is True
        assert bytes(received) == b"help\r"

        output = await asyncio.to_thread(
            client.request,
            "read",
            {"after_cursor": 0, "max_bytes": 100},
        )
        assert base64.b64decode(output["data_base64"]) == b"ok help response"
        assert output["text"] == "ok help response"
        released = await asyncio.to_thread(client.request, "release", {"lease_id": lease["lease_id"]})
        assert released["released"] is True
    finally:
        keep_open.set()
        await rpc_server.stop()
        await broker.stop()
        console_server.close()
        await console_server.wait_closed()
        console_socket.unlink(missing_ok=True)
        rpc_socket.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_rpc_rejects_wrong_token_and_policy_blocks_write(tmp_path: Path) -> None:
    rpc_socket = short_socket("rpc")
    store = ConsolePolicyStore(tmp_path / "policy.json")
    broker = ConsoleBroker(
        console_socket=short_socket("missing"),
        transcript=ConsoleTranscript(tmp_path / "transcript.bin"),
        policy_store=store,
    )
    server = ConsoleRpcServer(rpc_socket, "correct-token", broker)
    await server.start()
    try:
        wrong = ConsoleRpcClient(rpc_socket, "wrong-token", timeout_seconds=1)
        with pytest.raises(OldSunError) as raised:
            await asyncio.to_thread(wrong.request, "status")
        assert raised.value.code == "CONSOLE_RPC_UNAUTHORIZED"

        right = ConsoleRpcClient(rpc_socket, "correct-token", timeout_seconds=1)
        lease = await asyncio.to_thread(
            right.request,
            "acquire",
            {"owner": "codex", "reason": "test", "ttl_seconds": 30},
        )
        store.set_mcp_write_enabled(False, actor_id=42, actor_login="ryancnelson")
        with pytest.raises(OldSunError) as raised:
            await asyncio.to_thread(
                right.request,
                "send_key",
                {"lease_id": lease["lease_id"], "key": "ctrl-c", "reason": "test"},
            )
        assert raised.value.code == "CONSOLE_POLICY_BLOCKED"
    finally:
        await server.stop()
        rpc_socket.unlink(missing_ok=True)


def test_rpc_client_rejects_non_socket_path(tmp_path: Path) -> None:
    path = tmp_path / "rpc.sock"
    path.write_text("not a socket", encoding="utf-8")

    with pytest.raises(OldSunError) as raised:
        ConsoleRpcClient(path, "token", timeout_seconds=0.1).request("status")
    assert raised.value.code == "SOCKET_CONNECT_FAILED"
