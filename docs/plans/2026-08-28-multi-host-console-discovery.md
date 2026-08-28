# Multi-host Console Discovery Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Let the shared console discover live QEMU serial sockets on four allowlisted hosts and switch the one global browser/MCP console between them.

**Architecture:** Add typed host and target discovery in `console_discovery.py`, then put a `ConsoleTargetManager` in front of the existing single-owner broker. The web and MCP control APIs use opaque discovery IDs; the manager revalidates targets, switches the broker under one lock, persists process identity, and broadcasts target changes.

**Tech Stack:** Python 3.11+, asyncio, Starlette, xterm.js, fixed SSH argv adapters, pytest, pytest-asyncio.

---

### Task 1: Host registry and QEMU command-line parsing

**Files:**
- Create: `src/old_sun_mcp/console_discovery.py`
- Create: `tests/test_console_discovery.py`
- Modify: `src/old_sun_mcp/console_web.py`
- Modify: `tests/test_console_web.py`

**Step 1: Write failing parser and configuration tests**

Cover:

```python
def test_parse_serial_and_chardev_console_paths():
    assert parse_console_paths([
        "qemu-system-sparc64", "-serial",
        "unix:/tink/runs/demo/console.sock,server=on,wait=off",
    ]) == (PurePosixPath("/tink/runs/demo/console.sock"),)

    assert parse_console_paths([
        "qemu-system-sparc64", "-chardev",
        "socket,id=guestconsole,path=/tmp/demo.sock,server=on,wait=off",
        "-serial", "chardev:guestconsole",
    ]) == (PurePosixPath("/tmp/demo.sock"),)


def test_host_rejects_console_outside_allowed_roots():
    host = ConsoleHost(..., allowed_socket_roots=(PurePosixPath("/tink/runs"),))
    assert host.allows(PurePosixPath("/tink/runs/demo/console.sock"))
    assert not host.allows(PurePosixPath("/tmp/console.sock"))
    assert not host.allows(PurePosixPath("/tink/runs/../private.sock"))
```

Add `ConsoleWebConfig.from_env` tests for a JSON host registry containing the four initial hosts. Reject duplicate IDs, unsupported platforms, non-absolute roots, missing SSH targets, and unknown keys.

**Step 2: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/test_console_discovery.py tests/test_console_web.py -q
```

Expected: import or assertion failures because the discovery types do not exist.

**Step 3: Implement typed registry and parser**

Create immutable types:

```python
@dataclass(frozen=True)
class ConsoleHost:
    host_id: str
    label: str
    platform: Literal["linux", "darwin", "illumos"]
    ssh_target: str | None
    allowed_socket_roots: tuple[PurePosixPath, ...]
    lifecycle_argv: tuple[str, ...] | None = None
    discovery_timeout_seconds: float = 5.0
    connect_timeout_seconds: float = 5.0

    def allows(self, path: PurePosixPath) -> bool: ...


@dataclass(frozen=True)
class QemuProcess:
    pid: int
    started_at: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ConsoleTarget:
    target_id: str
    host_id: str
    socket_path: PurePosixPath
    pid: int
    started_at: str
    command: str
    qemu_name: str | None
    socket_mtime: float | None
```

Implement `parse_console_paths`, `parse_qemu_name`, lexical root validation, and strict JSON registry loading through `OLD_SUN_CONSOLE_HOSTS_JSON`. Preserve the legacy single socket/adapter configuration when no registry is supplied.

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_console_discovery.py tests/test_console_web.py -q
```

Expected: all focused tests pass.

**Step 5: Commit**

```bash
git add src/old_sun_mcp/console_discovery.py src/old_sun_mcp/console_web.py tests/test_console_discovery.py tests/test_console_web.py
git commit -m "feat: add console host registry and target parsing"
```

### Task 2: Bounded host discovery

**Files:**
- Modify: `src/old_sun_mcp/console_discovery.py`
- Modify: `tests/test_console_discovery.py`

**Step 1: Write failing discovery tests**

Use an injected async command runner. Cover:

- Linux, macOS, and illumos process-record parsing.
- Concurrent discovery with one successful host and one timeout.
- Filtering non-QEMU processes and paths outside allowed roots.
- Filtering paths that fail the remote socket validation command.
- Stable opaque target IDs derived from host, PID, start time, and socket path.
- Host-specific structured errors without suppressing successful results.

The result shape is:

```python
@dataclass(frozen=True)
class DiscoveryReport:
    targets: tuple[ConsoleTarget, ...]
    errors: Mapping[str, DiscoveryError]
```

**Step 2: Run the new tests and confirm failure**

Run:

```bash
uv run pytest tests/test_console_discovery.py -q
```

Expected: failures for missing discovery behavior.

**Step 3: Implement discovery runners**

Implement:

```python
class ConsoleDiscovery:
    def __init__(self, hosts, runner=run_command): ...
    async def discover(self) -> DiscoveryReport: ...
    async def revalidate(self, target: ConsoleTarget) -> ConsoleTarget: ...
    def connector(self, target: ConsoleTarget) -> ConsoleConnector: ...
```

The fixed platform scripts emit tab-separated PID, start time, and process
command. The Python parser uses `shlex.split`, extracts supported console
arguments, validates roots, and invokes a fixed socket check. SSH argv must
include `BatchMode=yes`, `ConnectTimeout=<n>`, and `-T`. Local Minnie profiles
run the same fixed scripts without SSH.

The connector is either `UnixConsoleConnector` or:

```python
ArgvConsoleConnector((
    "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
    "-T", host.ssh_target, "/usr/bin/socat", "-",
    f"UNIX-CONNECT:{target.socket_path}",
))
```

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_console_discovery.py -q
```

Expected: all discovery tests pass.

**Step 5: Commit**

```bash
git add src/old_sun_mcp/console_discovery.py tests/test_console_discovery.py
git commit -m "feat: discover live QEMU console sockets"
```

### Task 3: Persisted global target manager

**Files:**
- Create: `src/old_sun_mcp/console_targets.py`
- Create: `tests/test_console_targets.py`
- Modify: `src/old_sun_mcp/console_state.py`
- Modify: `src/old_sun_mcp/console_broker.py`
- Modify: `tests/test_console_state.py`
- Modify: `tests/test_console_broker.py`

**Step 1: Write failing persistence and switching tests**

Cover:

- State persists both `mcp_write_blocked` and selected target identity.
- Loading invalid state fails closed and clears the target.
- `BoundedHistory.clear()` removes output from the previous guest.
- Broker transport replacement keeps subscribers and emits disconnected then connected status.
- Target selection is serialized under concurrent calls.
- Selection revalidates the opaque target immediately before connection.
- A reused socket with a changed PID or start time is rejected.
- Target changes emit a structured event containing host, path, PID, and capabilities.
- Restart restoration connects only when the same process identity remains live.

**Step 2: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/test_console_state.py tests/test_console_broker.py tests/test_console_targets.py -q
```

Expected: failures for missing target persistence, history clearing, and manager.

**Step 3: Implement state, broker replacement, and manager**

Extend the atomic state payload:

```json
{
  "mcp_write_blocked": true,
  "selected_target": {
    "host_id": "ec2cicd",
    "socket_path": "/var/lib/niagara-ci/experiments/run/console.sock",
    "pid": 343827,
    "started_at": "2026-08-26T21:04:46Z"
  }
}
```

Add `ConsoleBroker.replace_transport(transport, clear_history=True)` and a
`ConsoleTargetManager` with `discover`, `current`, `select`, and `restore`.
The manager owns the global selection lock and broadcasts target events through
the existing broker subscription mechanism.

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_console_state.py tests/test_console_broker.py tests/test_console_targets.py -q
```

Expected: all focused tests pass.

**Step 5: Commit**

```bash
git add src/old_sun_mcp/console_state.py src/old_sun_mcp/console_broker.py src/old_sun_mcp/console_targets.py tests/test_console_state.py tests/test_console_broker.py tests/test_console_targets.py
git commit -m "feat: add global console target manager"
```

### Task 4: Web discovery and selection interface

**Files:**
- Modify: `src/old_sun_mcp/console_web.py`
- Modify: `src/old_sun_mcp/static/app.js`
- Modify: `src/old_sun_mcp/static/ui.css`
- Modify: `tests/test_console_web.py`

**Step 1: Write failing API and rendered-interface tests**

Cover authenticated routes:

```text
GET  /api/targets
GET  /api/target/current
POST /api/target/select
```

Assert origin checking on selection, opaque ID validation, stale-target status,
partial discovery errors, target metadata in `/api/state`, and capability-aware
lifecycle responses. Assert the HTML contains host/console selectors, Refresh,
Connect, and active-target fields.

**Step 2: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/test_console_web.py -q
```

Expected: route and markup assertions fail.

**Step 3: Implement routes and interface**

Wire the target manager into application lifespan and add the routes. Update
the WebSocket forwarder to send `target` events. In `app.js`, populate the host
and console selectors, require Connect for switching, print target-change
messages, clear the xterm buffer after a confirmed change, and update header
metadata. Disable lifecycle buttons when the target lacks the capability.

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_console_web.py -q
```

Expected: all web tests pass.

**Step 5: Commit**

```bash
git add src/old_sun_mcp/console_web.py src/old_sun_mcp/static/app.js src/old_sun_mcp/static/ui.css tests/test_console_web.py
git commit -m "feat: add multi-host console selector"
```

### Task 5: MCP discovery and target control

**Files:**
- Modify: `src/old_sun_mcp/console_control.py`
- Modify: `src/old_sun_mcp/console_client.py`
- Modify: `src/old_sun_mcp/service.py`
- Modify: `src/old_sun_mcp/server.py`
- Modify: `tests/test_console_control.py`
- Modify: `tests/test_console_client.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_server.py`

**Step 1: Write failing control and MCP tests**

Add control operations `list_targets`, `current_target`, and `select_target`.
Assert reads work while blocked. Assert `select_target` requires a reason and
returns `write_blocked` while `mcp_write_blocked` is true. Assert VM control is
also blocked before lifecycle execution. Register MCP tools:

```text
guest.console_targets
guest.console_select_target
```

**Step 2: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/test_console_control.py tests/test_console_client.py tests/test_service.py tests/test_server.py -q
```

Expected: missing operations and tool registrations fail.

**Step 3: Implement MCP operations and typed errors**

Inject the target manager into `ConsoleControlServer`. Add the read and mutate
operations, include current target metadata in every response, and map
`target_stale`, `target_not_found`, and `write_blocked` to typed `OldSunError`
codes. Enforce the block on every MCP mutation, including VM lifecycle calls.

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_console_control.py tests/test_console_client.py tests/test_service.py tests/test_server.py -q
```

Expected: all focused tests pass.

**Step 5: Commit**

```bash
git add src/old_sun_mcp/console_control.py src/old_sun_mcp/console_client.py src/old_sun_mcp/service.py src/old_sun_mcp/server.py tests/test_console_control.py tests/test_console_client.py tests/test_service.py tests/test_server.py
git commit -m "feat: expose console target control to MCP"
```

### Task 6: Deployment configuration and end-to-end verification

**Files:**
- Create: `examples/console-hosts-minnie.json`
- Modify: `docs/OPERATIONS.md`
- Modify: `README.md`
- Modify: `tests/test_packaging.py`

**Step 1: Add a failing packaging/configuration assertion**

Assert the example registry is packaged or checked in and contains the four
approved host IDs with the expected platform types and root structure.

**Step 2: Run the assertion and confirm failure**

Run:

```bash
uv run pytest tests/test_packaging.py -q
```

Expected: failure because the example registry is absent.

**Step 3: Add deployment example and operations documentation**

Document `OLD_SUN_CONSOLE_HOSTS_JSON`, SSH-agent requirements, per-host socket
roots, discovery failures, global selection behavior, MCP block semantics, and
the local Minnie startup command. The example must use no credentials.

**Step 4: Run full verification**

Run:

```bash
uv run pytest
uv build
git diff --check
```

Expected: all tests pass, wheel and sdist build, and no whitespace errors.

**Step 5: Run bounded live discovery on Minnie**

Start the console with the four-host registry and development auth. Verify:

- `/api/targets` returns without hanging when a host is unavailable;
- `ec2cicd` reports its live QEMU console socket;
- selecting `ec2cicd` updates the global header and connects the WebSocket;
- the MCP block prevents MCP selection and console writes;
- human selection remains available;
- no console input is sent during verification.

**Step 6: Commit**

```bash
git add examples/console-hosts-minnie.json docs/OPERATIONS.md README.md tests/test_packaging.py
git commit -m "docs: configure multi-host console discovery"
```
