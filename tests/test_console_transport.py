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
