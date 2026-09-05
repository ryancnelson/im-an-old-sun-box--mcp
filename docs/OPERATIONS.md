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

## Multi-host browser console

The maintained local launcher replaces temporary `/tmp` startup scripts:

```bash
.venv/bin/python -m old_sun_mcp.console_launcher \
  --hosts examples/console-hosts-minnie.json --port 8877
```

It binds only to loopback and enables local development authentication. Private
MCP/session credentials persist in `~/.local/state/old-sun-console/credentials.json`
with mode 0600. Load the MCP token through the caller's maintained credential
handoff; never pass it on a command line. `--state` and `--control-socket` preserve
existing deployment paths when migrating a running broker. After migration from
the old temporary launcher, MCP clients must load the new token. Browser cookies
from the previous signing key require a new local development login.

The dropdown refreshes ten seconds after each completed discovery. A new guest
appears without a page reload; Connect remains explicit. Biggie is included in
the sample registry, alongside the original lab hosts. Stopped pipeline guests
disappear without scanning stale run directories.

Docker discovery requires host-side Python 3, Docker permission, explicit
`docker_container_prefixes` and `docker_socket_roots`. The sample registry uses
the same root SSH identity on niagara-playbox as the pipelines. The fixed helper
reads Docker state and exact Linux process argv; it never reads container
environment variables or opens a console. Docker sockets are checked inside the
container and attached with `docker exec -i ... python3` using the bundled
stdlib Unix-socket relay (the guest image does not need socat). Interactive main-QEMU
containers with open stdin and TTY use `docker attach --sig-proxy=false` instead.
The latter shares Docker's terminal with any existing attached operator; it does
not provide exclusive writer arbitration. Stdio-only native QEMU and libvirt PTY
consoles are not socket targets and remain outside this provider.

Native-host and Docker errors are independent. A failed Docker query appears
under `host/docker` without hiding healthy host consoles. Host polling is bounded;
Docker-enabled profiles have a 20-second discovery deadline. Every connection
revalidates the selected instance. Replaced processes or sockets require a fresh
selection instead of silently switching a running terminal to another guest.

Run browser behavior tests with `node --test tests/console_directory.test.cjs`.

The browser console can discover live QEMU serial endpoints on a fixed list of
hosts. Use [the Minnie registry](../examples/console-hosts-minnie.json) as the
starting configuration. Review its socket roots and TCP ports before starting
the service. Discovery rejects Unix sockets outside `allowed_socket_roots` and
TCP endpoints outside `allowed_tcp_ports`. TCP serial servers must also bind to
loopback; wildcard and remotely reachable listeners are never accepted.

Minnie needs non-interactive SSH access to each remote `ssh_target`. The SSH
agent supplies credentials. Host-key checking uses the machine's existing SSH
configuration. Remote hosts also need `/bin/sh`, process inspection commands,
and `/usr/bin/socat` for Unix sockets or `/usr/bin/nc` for TCP endpoints.
Nothing is installed or copied to a remote host by the console service.

For local development authentication:

```bash
export OLD_SUN_CONSOLE_HOSTS_JSON="$(<examples/console-hosts-minnie.json)"
export OLD_SUN_CONSOLE_BIND=127.0.0.1
export OLD_SUN_CONSOLE_PORT=8876
export OLD_SUN_CONSOLE_PUBLIC_URL=http://127.0.0.1:8876
export OLD_SUN_CONSOLE_DEV_AUTH=1
export OLD_SUN_CONSOLE_MCP_TOKEN="$(openssl rand -hex 32)"
export OLD_SUN_CONSOLE_SESSION_SECRET="$(openssl rand -hex 32)"
export OLD_SUN_CONSOLE_STATE=/private/tmp/old-sun-console-state.json
export OLD_SUN_CONSOLE_CONTROL_SOCKET=/private/tmp/old-sun-console-control.sock
uv run old-sun-console
```

Do not set `OLD_SUN_CONSOLE_SOCKET` or `OLD_SUN_CONSOLE_ADAPTER_JSON` when
`OLD_SUN_CONSOLE_HOSTS_JSON` is set. Those variables remain available for the
legacy fixed-console configuration.

`GET /api/targets` inspects all configured hosts concurrently. A timeout or SSH
failure appears under that host's `errors` entry; results from other hosts are
still returned. Discovery begins with live QEMU processes and validates their
serial endpoints. Unix sockets are checked on the remote filesystem; TCP
targets are derived from the live QEMU argv and constrained by the host's exact
port allowlist. It does not scan run directories for stale socket files.

The selected target is global. Changing a selector in the browser does nothing
until Connect is pressed. A successful change clears buffered output from the
previous guest and updates every browser and MCP client. The service stores the
host, socket, PID, and process start time. It reconnects after a restart only if
those fields still identify the same process.

The "Block MCP typing" checkbox persists across browser and service restarts.
When checked, MCP clients can list targets, inspect the current target, and read
console output. MCP target changes, console writes, Break, Reset, Power, and
Start are rejected. Authenticated browser input and browser target selection
remain available.

The MCP process connects through the authenticated control socket. Configure
that socket in `.old-sun-mcp.toml`:

```toml
[console_control]
socket = "/private/tmp/old-sun-console-control.sock"
run = "multi-host-lab"
token_env = "OLD_SUN_CONSOLE_MCP_TOKEN"
timeout_seconds = 8
```

`guest.console_targets` returns discovered targets, host errors, and the active
target. `guest.console_select_target` requires an opaque target ID from that
result and a non-empty reason.

Lifecycle buttons require a `lifecycle_argv` in the selected host entry. The
adapter receives one final argument: `break`, `reset`, `powerdown`, `start`, or
`status`. Leave the field absent until the adapter is specific to that host and
tested against the intended QEMU process.
