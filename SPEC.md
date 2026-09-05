# I'm an Old Sun Box MCP — Specification

**Version:** 0.1.0-draft  
**Status:** Normative implementation contract  
**Date:** 2026-08-27

## 1. Purpose

This project provides an MCP server for investigating and operating a virtual
Sun Niagara laboratory. The Solaris or illumos SPARC guest is the primary
subject, while QEMU, the emulated machine, the debugger, and the VM host are
available as distinct evidence and control layers.

The server is an out-of-band control plane. Guest networking is evidence under
test and MUST NOT be required for discovery, observation, guest command
execution, debugger access, or VM control.

The primary workflow is cross-layer repair. Given a reproducible guest symptom
such as a userland command failing an ioctl, an investigation SHOULD preserve
competing ownership hypotheses across guest userland, the illumos kernel, the
guest device driver, QEMU's sun4v/device implementation, and lab wiring. Tools
MUST retain enough layer provenance to rerun the same discriminating test after
a patch and compare the evidence rather than merely compare impressions.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
to be interpreted as normative requirements.

## 2. Design principles

1. **Guest-first, not guest-only.** The agent reasons about the guest as its
   immediate operating subject but MAY cross into emulator, debugger, and host
   layers whenever a discriminating test requires it.
2. **Layer provenance is mandatory.** Every observation MUST identify the layer
   and concrete source that produced it.
3. **Out-of-band control.** Serial sockets, guest channels, QEMU monitor, GDB,
   and host tracing MUST remain usable when guest networking is absent or
   broken.
4. **Exact target identity.** A live operation MUST resolve one validated run
   and one exact QEMU process. Process-name-first targeting such as
   `pgrep qemu | head -1` is forbidden.
5. **Power with visible effects.** Expert operations are permitted. Their
   mutation class, intended effect, pre-state, and post-state MUST be explicit.
6. **Gilfoyle method.** Investigations SHOULD use competing falsifiable
   hypotheses, predicted observations, discriminating tests, and immediate fact
   recording.
7. **Bounded execution.** Command duration, output size, trace duration, and
   target scope MUST be bounded.
8. **Do not lie about cleanup.** Debugger detach, VM resume, trace teardown, and
   channel ownership MUST be proved or reported as unresolved.

## 3. System model

The MCP server recognizes these layers:

| Layer | Identifier | Examples |
|---|---|---|
| Laboratory | `lab` | run discovery, intent, capabilities |
| Guest | `guest` | Solaris shell, guest console, services, DTrace providers |
| Emulator | `emulator` | QEMU HMP/QMP, virtual devices, vCPU state |
| Debugger | `debugger` | GDB registers, memory, instructions, symbols |
| Host | `host` | QEMU process, scheduler, eBPF, perf, host I/O |
| Artifact | `artifact` | logs, manifests, captures, disk metadata |

The default deployment is a local stdio MCP process on the VM host:

```text
Codex client
    |
    | MCP stdio
    v
I'm an Old Sun Box MCP
    +-- run/manifests/logs
    +-- guest Unix-socket command adapter
    +-- QEMU HMP or QMP Unix socket
    +-- GDB remote stub
    +-- host process/eBPF/perf tools
```

An optional relay MAY carry MCP or backend requests between Ryan's primary Mac
and the VM host. A relay MUST preserve the same tool schemas and evidence
envelopes. The guest network MUST NOT be used as that relay.

## 4. Run identity and discovery

### 4.1 Run root

A **run root** is a configured directory containing zero or more run
directories. Configuration MUST explicitly list allowed run roots. The server
MUST NOT scan the entire filesystem for QEMU processes or sockets.

### 4.2 Valid run

A directory is a valid run when:

- its canonical path is contained by a configured run root;
- it is not a symlink escape from that root; and
- it contains at least one identity artifact: `run.manifest`, `qemu.pid`, or a
  configured manifest filename.

A live run SHOULD contain:

- `qemu.pid`
- `monitor.sock`
- `console.sock` and/or `console.log`
- `run.manifest`
- optional guest channel sockets
- optional `classifier-state.json`

### 4.3 Run selector

Tools that operate on a run accept a `run` string. It MAY be:

- a run name relative to exactly one configured root; or
- an absolute path contained by a configured root.

Ambiguous relative names MUST fail. A missing selector MAY use
`default_run` from configuration. It MUST NOT silently select the first live
QEMU process.

### 4.4 PID verification

Before a live process operation, the server MUST:

1. parse the run's PID file as one positive integer;
2. prove that the process exists;
3. obtain its command line where the host permits it; and
4. prove the command line refers to at least one artifact in the resolved run,
   unless the run profile declares another exact verification rule.

Failure to prove identity MUST stop the operation.

## 5. Configuration

The server reads TOML configuration. Search order is:

1. path supplied by `OLD_SUN_MCP_CONFIG`;
2. project-local `.old-sun-mcp.toml`;
3. `$XDG_CONFIG_HOME/old-sun-mcp/config.toml`; or
4. `~/.config/old-sun-mcp/config.toml`.

No configuration file is required to start the server or list tools. Live
operations without applicable configuration MUST return a typed configuration
error.

Example:

```toml
version = 1
default_run = "oi-workstation"
max_output_bytes = 262144
default_timeout_seconds = 30

[[run_roots]]
path = "/home/ryan/devel/masa-sun4v/ci/runs"

[paths]
classifier = "/home/ryan/devel/qemu-sun4v-illumos/tools/ci/classify-niagara-vm.py"
gdb = "/usr/local/bin/sparc64-unknown-elf-gdb"

[guest_adapters.maintenance]
kind = "argv"
socket = "console.sock"
argv = [
  "/home/ryan/devel/qemu-sun4v-illumos/tools/openindiana/r0-guest-command.exp",
  "{socket}", "{command}", "{timeout}"
]

[guest_adapters.channel1]
kind = "fresh-unix-shell"
socket = "chan1.sock"

[trace_recipes.tcg_stacks]
argv = ["/usr/local/libexec/old-sun-mcp/trace-tcg-stacks", "{pid}", "{duration}"]
max_duration_seconds = 15
requires_privilege = true
```

Configuration parsing MUST reject unknown top-level keys by default. A future
minor version MAY add an explicit compatibility mode.

Secrets MUST NOT be placed in this configuration. Environment variables passed
to configured adapters MUST be allowlisted by name.

## 6. Mutation model

Each tool belongs to one mutation class:

| Class | Identifier | Meaning |
|---|---|---|
| Observation | `observe` | Intended not to change target state |
| Reversible control | `reversible` | Pause/resume or similarly recoverable state |
| Disruptive | `disruptive` | Signals, debugger attachment, service changes |
| Destructive | `destructive` | Disk writes, snapshot deletion, irreversible state |

Observational tools MUST set MCP `readOnlyHint=true` when supported.
State-changing tools MUST set `readOnlyHint=false`. Destructive tools MUST set
`destructiveHint=true`.

Every non-observational call MUST include a non-empty `reason`. Destructive
operations are outside the 0.1 implementation scope and MUST NOT be exposed as
generic shell aliases.

Some hardware reads have acknowledge or clear-on-read effects. Such operations
MUST be classified according to their actual effect, not their command syntax.

## 7. Evidence envelope

Every tool returns one JSON object with these fields:

```json
{
  "schema_version": 1,
  "ok": true,
  "layer": "emulator",
  "operation": "qemu.hmp_query",
  "run": "oi-workstation",
  "observed_at": "2026-08-27T12:34:56.123456Z",
  "source": {
    "kind": "unix_socket",
    "ref": "monitor.sock"
  },
  "mutation": "observe",
  "data": {},
  "warnings": [],
  "error": null
}
```

### 7.1 Required behavior

- `observed_at` MUST be UTC.
- `source.ref` SHOULD be relative to the run when possible.
- Absolute private paths MAY be returned in local sessions but MUST be
  suppressible with `redact_paths=true`.
- Output truncation MUST add a warning containing original and returned byte
  counts.
- A tool failure MUST return `ok=false`, structured `error.code` and
  `error.message`, and any safe partial evidence.
- Exceptions and Python tracebacks MUST NOT be returned as the user-facing
  error body unless debug mode is explicitly enabled.

### 7.2 Error codes

Initial stable error codes are:

- `CONFIG_NOT_FOUND`
- `CONFIG_INVALID`
- `RUN_NOT_FOUND`
- `RUN_AMBIGUOUS`
- `RUN_OUTSIDE_ROOT`
- `RUN_INVALID`
- `PID_INVALID`
- `PID_NOT_RUNNING`
- `PID_IDENTITY_UNPROVED`
- `SOURCE_MISSING`
- `SOCKET_CONNECT_FAILED`
- `SOCKET_TIMEOUT`
- `COMMAND_TIMEOUT`
- `COMMAND_FAILED`
- `ADAPTER_UNAVAILABLE`
- `OUTPUT_TRUNCATED`
- `PRIVILEGE_REQUIRED`
- `CLEANUP_UNPROVED`
- `INVALID_ARGUMENT`
- `INTERNAL_ERROR`

## 8. Tool contracts

MCP names use dots. Implementations MAY expose underscore aliases for clients
that reject dots, but canonical evidence `operation` values use the dotted
names below.

### 8.1 `lab.list_runs`

**Mutation:** `observe`  
**Input:** optional `root`, `include_stopped=false`  
**Output data:** array of validated run summaries.

Each summary includes run name, declared intent when present, PID availability,
socket availability, and artifact freshness. This tool MUST NOT contact the
guest or mutate classifier state.

### 8.2 `lab.describe_run`

**Mutation:** `observe`  
**Input:** `run`  
**Output data:** sanitized manifest, resolved capabilities, artifact metadata,
and exact PID-verification status.

Manifest keys matching token, secret, password, credential, authorization, or
private-key patterns MUST be redacted.

### 8.3 `lab.classify`

**Mutation:** `observe` with local classifier-state write disclosed in source  
**Input:** `run`, optional `sample_seconds`, `expected`, and `desired`  
**Output data:** the existing semantic classifier JSON.

The adapter MUST invoke the configured project classifier rather than maintain
a competing state machine inside the MCP server. Because the existing
classifier writes retained state, the envelope MUST state this local metadata
effect even though guest and QEMU state are not intentionally changed.

### 8.4 `guest.console_tail`

**Mutation:** `observe`  
**Input:** `run`, optional `max_bytes`  
**Output data:** bounded decoded console text and file metadata.

The initial implementation reads a console log. It MUST NOT attach a second
reader to a live serial socket because that may consume bytes owned by the
interactive console process.

### 8.5 `guest.exec`

**Mutation:** `disruptive`  
**Input:** `run`, `command`, optional `adapter`, `timeout_seconds`, and required
`reason`  
**Output data:** stdout/stderr as available, guest exit status, adapter, socket,
duration, and timeout state.

Requirements:

- The adapter MUST be explicitly configured.
- The server MUST NOT silently fall back to SSH.
- The command MUST be passed as one adapter argument or framed stream, never
  interpolated into a host shell command.
- An `argv` adapter MUST execute without `shell=True`.
- A `fresh-unix-shell` adapter MUST require a socket that creates one fresh
  shell per connection. It MUST use a random marker to frame completion and
  exit status.
- A persistent interactive console socket MUST NOT be treated as a fresh shell.
- Timeouts MUST close the client side and report whether guest command
  termination is unknown.

### 8.6 `qemu.status`

**Mutation:** `observe`  
**Input:** `run`  
**Output data:** PID identity, process existence, monitor kind and availability,
and an HMP `info status` or QMP `query-status` result.

### 8.7 `qemu.hmp_query`

**Mutation:** `observe`  
**Input:** `run`, `command`, optional `timeout_seconds`  
**Output data:** bounded raw HMP response.

The implementation MUST maintain an allowlist of query prefixes. Initial
prefixes are `info`, `help`, `query-`, and `x/` only when the addressed device
or memory range is not known to acknowledge state. Unknown commands MUST be
rejected with guidance to use `qemu.hmp_control`.

### 8.8 `qemu.hmp_control`

**Mutation:** `reversible` or `disruptive` as classified  
**Input:** `run`, `command`, required `reason`, optional `timeout_seconds`  
**Output data:** pre-status, raw response, post-status, and classified effect.

The 0.1 release supports an explicit allowlist including `stop`, `cont`,
`system_reset`, `sendkey`, and loopback-only `gdbserver`. `quit` is excluded
until VM lifecycle contracts exist.

### 8.9 `host.process_sample`

**Mutation:** `observe`  
**Input:** `run`, optional `sample_seconds`  
**Output data:** two exact-PID samples and deltas for CPU ticks, process state,
read/write bytes, RSS where available, and wait channel.

### 8.10 `host.trace_capabilities`

**Mutation:** `observe`  
**Input:** optional `run`  
**Output data:** availability and versions of configured bpftrace, perf, GDB,
kernel facilities, symbols, and privilege mode.

Absence of a host capability MUST NOT be reported as evidence about guest
behavior.

### 8.11 `host.trace`

**Mutation:** `disruptive`  
**Input:** `run`, `recipe`, `duration_seconds`, required `reason`  
**Output data:** exact PID, recipe identity and digest, bounded output, duration,
exit status, and cleanup status.

Only configured named recipes are supported in 0.1. Duration MUST be at least
one second and no more than the recipe maximum. The PID placeholder MUST be an
independent argv element. `shell=True` is forbidden.

### 8.12 `debugger.capture`

**Mutation:** `disruptive`  
**Input:** `run`, optional `profile`, required `reason`  
**Output data:** stub setup, registers, nearby instructions, optional backtrace,
and cleanup proof.

The adapter MUST:

1. record QEMU pre-status;
2. enable or reuse a loopback-bound GDB stub through the exact run monitor;
3. run a bounded, configured SPARC-aware GDB batch;
4. execute detach/resume cleanup in a guaranteed finalization path;
5. query QEMU post-status; and
6. return `CLEANUP_UNPROVED` if it cannot prove the guest is detached or in the
   deliberately requested state.

An implementation MUST test cleanup behavior with fake monitor and debugger
processes before enabling this tool for a live run.

### 8.13 `evidence.record`

**Mutation:** `observe` with append-only artifact write  
**Input:** `run`, `investigation_id`, `layer`, `claim`, `source`, optional
`tool_result_digest`, and `notes`  
**Output data:** assigned evidence ID and record digest.

Records are JSON Lines under the configured ledger directory. Writes MUST use a
lock and append exactly one complete line. Claims are observations, not
conclusions, and MUST identify a source.

### 8.14 `evidence.read`

**Mutation:** `observe`  
**Input:** `run`, optional `investigation_id`, `after_id`, `limit`  
**Output data:** ordered evidence and hypothesis events.

### 8.15 `hypothesis.start`

**Mutation:** `observe` with append-only artifact write  
**Input:** `run`, `investigation_id`, `statement`, at least one `prediction`, and
at least one `discriminating_test`  
**Output data:** hypothesis ID and event digest.

### 8.16 `hypothesis.update`

**Mutation:** `observe` with append-only artifact write  
**Input:** `run`, `investigation_id`, `hypothesis_id`, `status`, evidence IDs,
and `reason`  
**Statuses:** `open`, `supported`, `weakened`, `falsified`, `unresolved`  
**Output data:** appended event ID and digest.

Updates MUST NOT overwrite earlier events. `falsified` requires at least one
evidence ID. `supported` is not equivalent to proved.

## 9. MCP server behavior

- The implementation language is Python 3.11 or newer.
- The reference server uses the official Python MCP SDK and stdio transport.
- The server MUST write protocol messages only to stdout. Diagnostics go to
  stderr.
- Server initialization instructions MUST summarize the guest-first,
  cross-layer, hypothesis-driven worldview within the first 512 characters.
- Tool results SHOULD use MCP structured output.
- Long operations MUST honor cancellation where supported.
- The server MUST be useful without root. Operations requiring privilege return
  `PRIVILEGE_REQUIRED` with the exact missing capability or configured command.
- The server MUST NOT attempt password prompts, interactive sudo, or secret
  discovery.

## 10. Security boundaries

1. All filesystem paths derived from input MUST be canonicalized and checked
   against configured roots.
2. Unix socket paths MUST be derived from a validated run or explicitly
   configured; arbitrary caller-supplied socket paths are forbidden.
3. Subprocesses MUST use argv arrays and `shell=False`.
4. Adapter environment variables MUST be allowlisted.
5. Outputs MUST redact configured secret patterns and MUST never include the
   process environment wholesale.
6. The server MUST NOT expose a generic root host shell in 0.1.
7. Guest DTrace and host eBPF/perf evidence MUST retain distinct layer
   provenance even when they describe the same event across the virtualization
   boundary.
8. Raw expert tools MAY be specified later only with exact-target, timeout,
   output-bound, mutation, and cleanup contracts.
9. The QEMU monitor MUST remain bound to a Unix socket or loopback interface.
10. A GDB TCP listener MUST bind to loopback unless the operator explicitly
   configures another protected transport.

## 11. Persistence and concurrency

- Evidence and hypothesis ledgers are append-only JSON Lines.
- Each event contains an ID, UTC timestamp, investigation ID, event type,
  payload, and SHA-256 digest of the canonical event payload.
- Writers MUST take an advisory lock for the append.
- Partial trailing lines are treated as corruption and reported; they are not
  silently ignored.
- Concurrent observational calls are permitted.
- Calls that share an interactive guest adapter, HMP socket, debugger, or trace
  target MUST serialize per run and resource.

## 12. Logging

Operational logs go to stderr and contain:

- operation name;
- run identity;
- duration;
- success/failure code; and
- mutation class.

Logs MUST NOT contain secret values, full environment dumps, or unredacted
command output. Commands MAY be logged only when configuration does not mark
them sensitive.

## 13. Packaging

The repository MUST provide:

- `pyproject.toml` with an `old-sun-mcp` console entry point;
- Python package `old_sun_mcp`;
- example TOML configuration without private paths or secrets;
- unit tests requiring no live VM, root, network, or destructive disk;
- opt-in live smoke-test documentation;
- Codex configuration example for a stdio MCP server; and
- operator documentation for capability and privilege setup.

## 14. Conformance tests

The automated suite MUST prove:

1. Configuration search order, strict parsing, and safe missing-config startup.
2. Run-root containment, symlink escape rejection, ambiguous-name failure, and
   invalid PID rejection.
3. Secret-key redaction in manifests.
4. Evidence envelope shape, UTC timestamps, stable errors, and explicit
   truncation warnings.
5. HMP query/control classification plus HMP and QMP socket behavior using fake
   Unix sockets.
6. Guest adapter argv integrity, nonzero guest exit handling, transport error,
   and timeout behavior without `shell=True`.
7. Exact PID verification and two-sample host deltas using fixtures or a
   controlled child process.
8. Ledger locking, append-only history, digest stability, corruption detection,
   and hypothesis transition validation.
9. Trace recipe PID/duration bounds and cleanup using fake executables.
10. Debugger cleanup on success, timeout, malformed output, and debugger
    failure using fake monitor/GDB fixtures.
11. MCP server startup and tool enumeration over stdio.
12. Existing tests leave no child processes, Unix sockets, or modified fixture
    state behind.

## 15. Initial implementation boundary

The first implementation following this SPEC MUST deliver:

- configuration and validated run discovery;
- common evidence envelopes and stable errors;
- `lab.list_runs`, `lab.describe_run`, `guest.console_tail`, `guest.exec`,
  `qemu.status`, `qemu.hmp_query`, `qemu.hmp_control`,
  `host.process_sample`, `host.trace_capabilities`, and named `host.trace`;
- append-only evidence and hypothesis tools;
- debugger adapter interfaces and fully tested cleanup orchestration;
- a working stdio MCP server, examples, and automated tests.

Live eBPF recipes, live SPARC GDB profiles, destructive disk operations, VM
lifecycle, general QMP tools, and a cross-host relay MAY be added after the core
is proven. Their interfaces are reserved by this SPEC but require host-specific
validation before being claimed as working. `qemu.status` MAY use the typed QMP
`query-status` command when the run profile selects QMP.

### 15.1 Wedge rollover direction

A future lifecycle workflow SHOULD treat a wedged VM as an evidence source,
not as the only machine available for continued work. Its transaction is:

1. identify and deliberately freeze the exact run;
2. capture and hash the configured run inputs, console history, emulator state,
   guest memory or crash dump where supported, and tool provenance;
3. verify that the immutable capture is durable and readable;
4. enqueue that capture for named offline analyzers and interactive debugging;
5. launch a replacement from explicitly selected, known inputs; and
6. prove the replacement's run identity and boot progress.

The implementation MUST NOT terminate or overwrite the wedged run before step
3 succeeds. Capture success and replacement success are separate facts. A
failure in either phase MUST preserve enough state to retry safely. Lifecycle
tools require a reason, exact run selectors, idempotency keys, and an operator-
configured launch profile; they MUST NOT guess which disk image to reuse.

### 15.2 Authenticated shared console

An optional web console MAY own a validated run's `console.sock` and provide
browser and MCP clients with a shared view. It MUST preserve the out-of-band
control boundary and MUST NOT depend on guest networking.

The current deployment target for this broker is loopback-only. The
`console.unix.wtf` origin is reserved for the static Tailcat application in
Section 15.3. If this authenticated broker is deployed publicly in the future,
it MUST use a distinct origin and satisfy the following public-service rules.

The public HTTP service MUST bind to loopback behind a TLS reverse proxy. Human
access MUST use GitHub OAuth authorization-code flow and MUST compare both the
returned login and immutable numeric user ID with configured allowlist values.
An unlisted identity MUST receive no console history, run metadata, or control
state. OAuth state parameters and secure, HTTP-only session cookies are
required.

The broker is the only process that MAY own the QEMU console transport while it
is running. The transport MAY be a local Unix socket or a fixed configured argv
adapter that reaches a console on an SSH-accessible host. Adapter arguments
MUST NOT be derived from browser or MCP input. The broker MUST serialize
writes, retain bounded console history, reconnect after an interruption, and
expose connection state without claiming that the guest is healthy.

Human browser sessions MAY always write console bytes. MCP access MUST use a
separate authenticated local control socket. A persistent operator setting
MUST be able to block MCP writes without blocking MCP reads or human writes.
The default is blocked. Every MCP status and write response MUST include the
current block state; a blocked write MUST fail before sending any byte to the
guest. The setting MUST survive browser disconnects and broker restarts and
MUST be written atomically with restrictive permissions.

Neither the OAuth client secret, session signing secret, nor MCP control token
may appear in TOML, logs, process arguments, repository files, or browser
responses. Production startup MUST fail closed when any required secret or
identity pin is absent.

A development mode MAY bypass OAuth only when the HTTP listener is explicitly
bound to an IP loopback address. Startup MUST reject development mode on a
wildcard, hostname, or non-loopback bind.

### 15.3 Tailcat console transport

An optional console-sharing helper MAY make a serial-console Unix stream
socket available to a remote browser or MCP agent through Tailcat. The console
source MAY be QEMU, VMware, UTM, a container, a physical serial adapter, or any
other producer that can present the same byte-stream contract. Provisioning
and source discovery are outside the first implementation boundary.

The hosted application MUST be static. Tailcat MUST run inside the browser,
and console bytes MUST travel between the browser and local helper without
passing through the static application's HTTP origin. The page MUST NOT send a
Tailcat address or console contents to analytics, error reporting, server APIs,
URLs, cookies, or browser storage. The address MUST remain in page memory and
MUST be cleared by reload or navigation.

The canonical hosted origin is `https://console.unix.wtf/`. It MUST serve only
the static application and MUST NOT expose the authenticated broker from
Section 15.2, a console API, or a server-side Tailcat process.

The publisher MUST accept exactly one of two explicit modes: connect to an
existing Unix stream socket, or create a Unix stream socket and wait for its
producer. Listen mode MUST refuse to replace a path that is not a socket and
MUST remove only a socket created by the current publisher process. The publisher
MUST relay bytes unchanged in both directions and MUST propagate EOF and
half-close without inventing terminal framing.

Each publisher start MUST create a fresh in-memory Tailcat server key and address.
The publisher MUST NOT persist the key or reuse an address after restart. The
address is the sole session capability; the static site requires no account or
login. The publisher MUST allow only one active consumer connection, MUST
reject a second simultaneous connection, and MAY accept a replacement after
the active browser or MCP session disconnects. Exiting the publisher MUST close
the Tailcat server, the console connection, and any listener it created.

The browser client MUST use a pinned, reviewed Tailcat WebAssembly build and a
bounded xterm.js scrollback. It MUST disclose connection progress, DERP-only
browser transport, disconnection, and terminal errors without claiming that
the console source or guest is healthy. Tailcat's public DERP service MUST be
treated as best-effort infrastructure with no availability or throughput
guarantee. The design MAY later accept a configured DERP map, but MUST NOT
silently turn a page-supplied URL into executable or privileged local input.

The MCP distribution MAY include a native Tailcat client as a managed helper
binary. When present, Tailcat is a built-in console transport: the user MUST
NOT need a separate Tailcat installation or command. An external provisioner
MAY return a logical run identity and fresh Tailcat address for runtime attach;
the MCP MUST NOT depend on how that run was created.

Runtime attach MUST require a reason and MUST return an opaque local session
identifier. The Tailcat address MUST remain separate from run identity and
MUST NOT appear in process arguments, environment variables, persistent
configuration, evidence records, envelopes, logs, tracebacks, or error text.
The MCP MAY pass it to the managed client through a private inherited pipe that
is closed immediately after startup.

An attached session MUST support status, bounded read, reason-required write,
and detach. Console history MUST remain bounded and in memory. Detach and MCP
shutdown MUST close the managed client and prove bounded child-process cleanup.
Transport loss MUST disable writes and return a typed error without claiming
that the remote run stopped. Browser and MCP consumers share the publisher's
one-client limit; neither receives priority or preempts the other.

## 16. Definition of done

Version 0.1 is done when:

- all Section 15 capabilities are implemented;
- the conformance suite passes on macOS and the intended modern VM host;
- no test depends on guest networking or a live guest;
- a dry-run fixture investigation can create hypotheses, collect guest/QEMU/host
  evidence, falsify one hypothesis, and read the immutable history;
- an opt-in live smoke test describes exact preconditions and performs no
  destructive action;
- every shipped tool returns the evidence envelope and correct mutation hints;
- the README links to this SPEC and accurately distinguishes implemented from
  planned capabilities; and
- the implementation is committed and published without secrets, private
  captures, host-specific paths, or generated VM artifacts.
