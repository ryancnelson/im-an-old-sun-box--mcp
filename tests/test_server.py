import pytest

from old_sun_mcp.config import Config
from old_sun_mcp.server import create_server


@pytest.mark.asyncio
async def test_server_enumerates_canonical_tools() -> None:
    server = create_server(Config())
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert {
        "lab.list_runs", "lab.describe_run", "guest.console_tail", "guest.exec",
        "qemu.status", "qemu.hmp_query", "qemu.hmp_control",
        "host.process_sample", "host.trace_capabilities", "host.trace",
        "debugger.capture", "evidence.record", "evidence.read",
        "hypothesis.start", "hypothesis.update",
    } <= names
