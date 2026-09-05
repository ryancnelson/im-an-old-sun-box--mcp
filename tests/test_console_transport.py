import sys

import pytest

from old_sun_mcp.console_transport import ArgvConsoleConnector


@pytest.mark.asyncio
async def test_argv_transport_is_bidirectional_without_a_shell() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write(b'remote-ready\\n'); sys.stdout.buffer.flush(); "
        "data=sys.stdin.buffer.read(4); sys.stdout.buffer.write(data); sys.stdout.buffer.flush()"
    )
    connector = ArgvConsoleConnector((sys.executable, "-c", script))
    endpoint = await connector.connect()
    assert await endpoint.reader.readline() == b"remote-ready\n"
    endpoint.writer.write(b"ping")
    await endpoint.writer.drain()
    assert await endpoint.reader.readexactly(4) == b"ping"
    await endpoint.close()


def test_argv_transport_rejects_empty_argv() -> None:
    with pytest.raises(ValueError):
        ArgvConsoleConnector(())


@pytest.mark.asyncio
async def test_adapter_failure_is_reported_instead_of_connected():
    connector = ArgvConsoleConnector((sys.executable, "-c", "import sys; sys.stderr.write('Connection refused'); sys.exit(7)"),
                                     ready_marker=b"OLD_SUN_CONSOLE_READY")
    with pytest.raises(ConnectionError, match="Connection refused"):
        await connector.connect()


@pytest.mark.asyncio
async def test_container_relay_connects_without_socat_and_preserves_bytes():
    import asyncio
    import tempfile
    from pathlib import Path
    from old_sun_mcp import console_socket_relay
    with tempfile.TemporaryDirectory(prefix="relay-", dir="/tmp") as directory:
        path = str(Path(directory) / "s")
        async def echo(reader, writer):
            while data := await reader.read(1024):
                writer.write(data)
                await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_unix_server(echo, path=path)
        try:
            connector = ArgvConsoleConnector((sys.executable, console_socket_relay.__file__, path),
                                             ready_marker=b"OLD_SUN_CONSOLE_READY")
            endpoint = await connector.connect()
            try:
                data = b"test\x00\xff\r\n\x03"
                endpoint.writer.write(data)
                await endpoint.writer.drain()
                assert await asyncio.wait_for(endpoint.reader.readexactly(len(data)), 2) == data
            finally:
                await endpoint.close()
        finally:
            server.close()
            await server.wait_closed()
