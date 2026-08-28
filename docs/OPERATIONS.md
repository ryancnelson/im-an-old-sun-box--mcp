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

## Shared console deployment on ec2trib

The QEMU launcher creates a per-run `console.sock` and updates
`/tink/runs/oi-basecamp-latest`. Do not attach a second `socat`, terminal
bridge, or web proxy after the broker starts. The broker must be QEMU's only
serial client.

Build the wheel on a development host:

```bash
uv sync --extra test
uv run pytest -q
uv build --wheel
```

Copy the wheel and `deploy/ec2trib` directory to the Tribblix host, then run:

```bash
deploy/ec2trib/install.sh dist/im_an_old_sun_box_mcp-0.1.0-py3-none-any.whl
```

The installer creates `/opt/old-sun-console/venv` and installs the `console`
extra. That extra deliberately excludes the MCP SDK and Pydantic so the broker
works on Tribblix Python 3.13 without compiling Rust. Install the `mcp` extra in
the environment that runs the stdio MCP server; it may be a separate modern
host or virtual environment.

Create `/etc/old-sun-console/console.env` from
`deploy/ec2trib/console.env.example`, owned by root and mode 0600. Secret
values must come from Doppler or another external secret store. Required
values are:

- GitHub OAuth client ID and secret;
- an unpredictable session-signing secret of at least 32 bytes; and
- an independent broker bearer token for MCP.

The GitHub OAuth application callback is the exact public base URL followed by
`/auth/callback`. Admission is restricted to GitHub numeric account ID
`347171` and login `ryancnelson`. Do not substitute the login string for the
numeric check.

Replace the hostname and certificate paths in
`deploy/ec2trib/nginx-old-sun-console.conf`, include it from nginx's `http`
configuration, and test the nginx configuration before reload. The application
listener stays on `127.0.0.1:8765`; nginx owns public TLS and WebSocket upgrade.
The OAuth callback access log remains disabled because its query contains a
short-lived code.

Install the SMF manifest only after the environment file and HTTPS proxy are
ready:

```bash
svccfg import deploy/ec2trib/old-sun-console.xml
svcadm enable application/old-sun-console
svcs -xv application/old-sun-console
```

The start method resolves `oi-basecamp-latest` once, proves that it remains
inside `/tink/runs`, checks the serial socket and PID file, and passes the exact
run directory to the broker. It does not start or stop QEMU.

## MCP console client

The stdio MCP process needs the same bearer token in the environment named by
`console.token_env`. Its TOML profile points at the broker's private Unix
socket:

```toml
[console]
rpc_socket = "/tink/vm-state/oi-basecamp/console-broker.sock"
token_env = "OLD_SUN_CONSOLE_MCP_TOKEN"
run = "oi-basecamp-latest"
```

Use the console tools in this order for writes:

1. `console.status`
2. `console.read` from a remembered cursor
3. `console.acquire` with an owner, reason, and short TTL
4. `console.write` or `console.send_key` with a reason
5. `console.expect` from the pre-write cursor
6. `console.release` in cleanup

The human remains able to type throughout. When `Block MCP keyboard input` is
checked, reads and expect still work, but the next MCP write returns
`CONSOLE_POLICY_BLOCKED`. Do not retry writes until the human changes the
policy.

## Console verification

Before enabling public access, verify:

- `GET /healthz` reports `console_connected=true` on loopback;
- only the configured GitHub account reaches the terminal;
- browser input and MCP input appear in one ordered transcript;
- the human can type Ctrl-C while an MCP lease exists;
- checking the policy box blocks the next MCP write immediately;
- the checked state survives service and QEMU restarts;
- stopping the broker leaves QEMU running; and
- QMP still reports the expected run state.

The first live RPC and installed-web checks are recorded in
`docs/live-validation/2026-08-28-console-broker.md`. OAuth, nginx, SMF, browser
input, and persistent-policy restart checks remain unproved until the public
deployment has real credentials and TLS.
