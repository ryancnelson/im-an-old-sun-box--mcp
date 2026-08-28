import pytest
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from old_sun_mcp.config import Config
from old_sun_mcp.server import create_server


@pytest.mark.asyncio
async def test_server_enumerates_canonical_tools() -> None:
    server = create_server(Config())
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert {
        "lab.list_runs", "lab.describe_run", "guest.console_tail", "guest.exec",
        "guest.console_status", "guest.console_read", "guest.console_write",
        "qemu.status", "qemu.hmp_query", "qemu.hmp_control",
        "host.process_sample", "host.trace_capabilities", "host.trace",
        "debugger.capture", "evidence.record", "evidence.read",
        "hypothesis.start", "hypothesis.update",
    } <= names


@pytest.mark.asyncio
async def test_real_stdio_initialize_and_list_tools() -> None:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "old_sun_mcp"])
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
    assert initialized.serverInfo.name == "I'm an Old Sun Box"
    assert any(tool.name == "lab.list_runs" for tool in tools.tools)
