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
They never silently fall back to SSH. HMP and QMP remain on Unix sockets. A live
GDB profile is restricted to a loopback TCP endpoint or a safe run-relative
Unix socket and fixed SPARC evidence commands.
Use `gdb-multiarch` or another GDB build that accepts the configured SPARC
architecture; the ordinary Ubuntu GDB build may not include it.

## Safe failure behavior

All calls return a structured evidence envelope. Timeouts bound command and
socket waits. Output is byte-bounded and truncation is disclosed. State-changing
operations require a reason. Debugger and trace operations never claim cleanup
unless it was verified.

Debugger capture starts the stub through the exact run's monitor, executes a
bounded batch, closes the debugger process, and restores the recorded QEMU
state. It returns `CLEANUP_UNPROVED` if the state check fails. The semantic
classifier still returns `ADAPTER_UNAVAILABLE` until its project-specific argv
contract is configured and tested.

Newer QEMU launchers can configure `monitor_kind = "qmp"` and a run-relative
`monitor_socket`. The current QMP surface is deliberately small: typed
`query-status`, plus `stop` and `cont` used only for debugger cleanup. The MCP
does not expose arbitrary QMP execution.
