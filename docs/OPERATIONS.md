# Operator Guide

## Install and run

Python 3.11 or newer is required. For development:

```bash
uv sync --extra test
uv run old-sun-mcp
```

The server uses MCP over stdio. Stdout is reserved for protocol messages;
diagnostics belong on stderr.

Copy `examples/config.toml` to `.old-sun-mcp.toml` and adapt only the paths and
named adapters needed by the host. Configuration search order is the explicit
`OLD_SUN_MCP_CONFIG` path, project-local config, XDG config, then the standard
home config directory. The server starts without configuration so clients can
enumerate tools, but live operations return `CONFIG_NOT_FOUND`.

## Identity and privileges

Every live run resolves inside an allowlisted run root. `qemu.pid` must contain
one live positive PID and that process's command line must reference an artifact
inside the resolved run. Do not replace this with process-name discovery.

The server never prompts for sudo and does not discover credentials. Named host
trace recipes declare whether privilege is required. Arrange the narrowest
host capability outside the MCP process, then confirm it with
`host.trace_capabilities`.

Guest commands use only configured argv or fresh-shell Unix-socket adapters.
They never silently fall back to SSH. HMP remains on a Unix socket. A live GDB
profile must use loopback or an equivalently protected transport.

## Safe failure behavior

All calls return a structured evidence envelope. Timeouts bound command and
socket waits. Output is byte-bounded and truncation is disclosed. State-changing
operations require a reason. Debugger and trace operations never claim cleanup
unless it was verified.

The current 0.1 core includes debugger cleanup orchestration tested with fakes,
but deliberately returns `ADAPTER_UNAVAILABLE` for live debugger capture until
a SPARC GDB profile is validated on the VM host. The semantic classifier does
the same until its project-specific argv contract is configured and tested.

