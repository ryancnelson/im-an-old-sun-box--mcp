# Multi-host QEMU console discovery

## Goal

Let the shared console discover and connect to live QEMU serial sockets on
`ec2cicd`, `minnie-2-2`, `niagara-playbox`, and `ec2trib`. Minnie has SSH agent
access to every remote host. The selected console is global: every browser and
the MCP observes and controls the same QEMU instance.

This is a single-user operations tool. It favors a fixed host allowlist,
visible state, and low setup cost over multi-tenant policy or a remote agent on
each host.

## Selected design

The broker discovers QEMU processes through fixed local or SSH commands. It
parses each live process command line for Unix serial sockets, validates every
socket against the host's allowed roots, and presents the results in the web
interface. Stale sockets are hidden from the normal list.

The operator selects a host and console, then presses Connect. One target
manager stops the current transport, connects the selected transport, updates
the shared state, and notifies all browser and MCP clients. Changing a selector
without pressing Connect has no effect.

No service or discovery helper must be installed on the remote hosts. The
broker sends a versioned, fixed discovery script over SSH stdin. Platform-
specific scripts support Linux, macOS, and illumos process inspection.

## Host registry

Each configured host has:

- a stable host ID and display label;
- a platform type: `linux`, `darwin`, or `illumos`;
- a fixed SSH target, or an explicit local transport;
- one or more permitted socket roots;
- an optional lifecycle adapter;
- connection and discovery timeouts.

An example host profile is:

```toml
[[console_hosts]]
id = "ec2cicd"
label = "ec2cicd"
platform = "linux"
ssh_target = "root@ec2cicd"
allowed_socket_roots = ["/var/lib/niagara-ci/experiments"]
connect_timeout_seconds = 5
discovery_timeout_seconds = 5
```

The initial registry contains these hosts:

| Host | Platform | Expected roots |
| --- | --- | --- |
| `ec2cicd` | Linux | `/var/lib/niagara-ci/experiments` |
| `minnie-2-2` | macOS | configured local run roots and `/tmp` |
| `niagara-playbox` | Linux | `/mnt/disk-images/runs`, `/tmp`, and configured project run roots |
| `ec2trib` | illumos | `/tink/runs` |

The checked-in configuration documents the structure. Machine-specific roots
remain in deployment configuration when they contain private paths.

## Discovery

Discovery starts with live QEMU processes. It does not scan the filesystem for
arbitrary `*.sock` files.

Linux discovery reads `/proc/<pid>/cmdline`. macOS discovery uses `ps` with a
full command line. illumos discovery uses `pgrep`, `pargs`, and `ps`. The parser
recognizes the serial forms currently used by the project, including:

```text
-serial unix:/path/console.sock,server=on,wait=off
-chardev socket,id=guestconsole,path=/path/console.sock,server=on,wait=off
-serial chardev:guestconsole
```

Each result contains:

- host ID;
- socket path;
- QEMU PID;
- process start time;
- process command line;
- QEMU name when `-name` is present;
- socket modification time;
- lifecycle and statistics capabilities.

The server assigns an opaque target ID to each result. The browser submits only
that ID. Before connecting, the server repeats the process identity, socket
type, and allowed-root checks. A missing process, changed start time, replaced
socket, or disallowed path invalidates the target.

Discovery runs concurrently with a bounded timeout per host. One unreachable
host does not suppress results from the others. The UI reports host-specific
errors such as SSH authentication failure, timeout, unavailable process tools,
or no live console sockets.

## Global target manager

The target manager owns the active target and the console broker. Target
changes run under one async lock:

1. Validate the selected discovery result again.
2. Broadcast a target-change event to browsers and MCP clients.
3. Stop the current console transport.
4. Clear the console history buffer.
5. Create the selected local or SSH/socat transport.
6. Connect the broker.
7. Persist the selected target identity.
8. Broadcast the new connection metadata.

The persisted identity contains the host ID, socket path, QEMU PID, and process
start time. On service restart, the target manager reconnects only when all
fields still identify the same process. Socket-path reuse never selects a new
QEMU process automatically.

The broker never falls back to another target. A lost socket leaves the target
selected and reports it as disconnected. The operator can refresh discovery
and choose the replacement.

## Browser interface

The header gains:

- a host selector;
- a console selector;
- Refresh and Connect buttons;
- the active host, socket, transport, PID, process age, and statistics;
- capability-aware Break, Reset, Power, and Start controls.

The console selector shows the QEMU name, PID, process age, and socket path.
Changing either selector does not interrupt the active console. Connect makes
the change explicit.

Target changes and connection failures appear as timestamped terminal system
messages. The terminal buffer is cleared between targets so output from two
guests cannot be mistaken for one session.

Lifecycle buttons are disabled when the selected host lacks a lifecycle
adapter. Statistics failures do not disconnect a working console.

## MCP behavior

The control protocol adds operations to:

- discover and list targets;
- read per-host discovery failures;
- read the current target;
- select a target.

The current target is global. A target change made by the browser or MCP is
reported to every client.

`mcp_write_blocked` remains persistent and defaults to `true`. While blocked,
the MCP may discover targets, inspect status, and read console output. The
server rejects MCP console writes, target changes, Break, Reset, Power, and
Start. Each rejection reports that operator control is blocking the action.

Authenticated human browser input and target selection remain available while
MCP writes are blocked.

## Security properties

- Hosts come only from the server-side registry.
- SSH targets and command arguments are fixed configuration values.
- Socket paths come only from validated discovery results.
- Socket paths must resolve beneath an allowed root before discovery output and
  again before connection.
- SSH uses `BatchMode=yes`, a connection timeout, and the machine's existing
  known-hosts policy.
- Discovery scripts are fixed application resources sent over SSH stdin.
- The browser cannot submit shell fragments, hostnames, or raw socket paths.
- Target selection requires the existing authenticated browser session or MCP
  token.
- State-file permissions remain private to the service account.

## Failure behavior

- Unreachable host: show the host error and retain results from other hosts.
- Vanished process or socket: reject selection as stale and request refresh.
- Busy serial socket: report that another client owns the QEMU chardev.
- Missing remote `socat`: report a transport dependency failure.
- Connection loss: keep the selected target, mark it disconnected, and use the
  broker's bounded reconnect behavior only for the same validated process.
- Service restart: reconnect only to an identical persisted process.
- Statistics failure: display unavailable statistics without changing the
  console connection.
- Lifecycle failure: report the command result without dropping the console.

## Testing

Unit tests cover:

- Linux, macOS, and illumos discovery output parsing;
- supported QEMU serial command-line forms;
- allowed-root and symlink validation;
- opaque target IDs and stale-result rejection;
- serialized global target changes;
- history clearing between targets;
- target persistence and PID-reuse rejection;
- browser and MCP target-change notifications;
- MCP block enforcement for every mutating operation;
- lifecycle and statistics capability changes.

Integration tests use fake SSH commands, Unix sockets, and QEMU-like process
records. They cover partial host failure, socket contention, reconnects, and a
browser that remains connected while the broker changes targets.

An optional live test discovers a Minnie QEMU socket, connects it, reads a
known console marker, and disconnects without sending guest input.

## Rejected alternatives

- A static list of complete socket paths becomes stale whenever a run directory
  changes.
- A remote agent on every host adds installation, versioning, and supervision
  work that discovery over existing SSH access does not need.
- Broad filesystem scans include stale sockets and cannot prove that a live
  QEMU process owns them.
- Per-browser target selection would allow the human and MCP to operate
  different guests while sharing one service and one write-control policy.
- Automatic fallback could connect the operator to the wrong VM after a crash
  or socket-path reuse.
