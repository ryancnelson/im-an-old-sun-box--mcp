"""Official MCP SDK stdio server."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import Config, load_config
from .service import OldSunService


INSTRUCTIONS = "You are investigating an old Solaris/illumos SPARC box. Begin at the guest symptom, but cross into QEMU, debugger, firmware, and host layers when a discriminating test calls for it. Preserve layer provenance, exact run identity, competing falsifiable hypotheses, bounded execution, and proved cleanup. Guest networking is evidence under test, never a control-plane prerequisite."


def create_server(config: Config | None = None) -> FastMCP:
    service = OldSunService(config or load_config())
    server = FastMCP("I'm an Old Sun Box", instructions=INSTRUCTIONS)
    observe = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    mutate = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

    def register(name: str, function, annotations: ToolAnnotations) -> None:
        server.tool(name=name, annotations=annotations, structured_output=True)(function)

    register("lab.list_runs", service.lab_list_runs, observe); register("lab.describe_run", service.lab_describe_run, observe); register("lab.classify", service.lab_classify, observe)
    register("guest.console_tail", service.guest_console_tail, observe); register("guest.exec", service.guest_exec, mutate)
    register("qemu.status", service.qemu_status, observe); register("qemu.hmp_query", service.qemu_hmp_query, observe); register("qemu.hmp_control", service.qemu_hmp_control, mutate)
    register("host.process_sample", service.host_process_sample, observe); register("host.trace_capabilities", service.host_trace_capabilities, observe); register("host.trace", service.host_trace, mutate)
    register("debugger.capture", service.debugger_capture, mutate)
    register("evidence.record", service.evidence_record, observe); register("evidence.read", service.evidence_read, observe)
    register("hypothesis.start", service.hypothesis_start, observe); register("hypothesis.update", service.hypothesis_update, observe)
    register("console.status", service.console_status, observe); register("console.read", service.console_read, observe)
    register("console.acquire", service.console_acquire, mutate); register("console.write", service.console_write, mutate)
    register("console.send_key", service.console_send_key, mutate); register("console.expect", service.console_expect, observe)
    register("console.release", service.console_release, mutate)
    return server


def run() -> None:
    create_server().run(transport="stdio")
