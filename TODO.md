# Project TODOs

This is the project's one canonical backlog. If work matters, it gets a stable
ID here before implementation begins. GitHub issues may discuss an item, but
they do not replace this file.

## Status vocabulary

- `idea`: worth preserving, not yet shaped enough to schedule
- `ready`: scoped with acceptance criteria and no known blocker
- `active`: has one named branch and an owner
- `blocked`: cannot proceed; the blocking condition is written down
- `done`: merged, verified, and reflected in docs
- `declined`: deliberately not doing it, with a reason

Only one entry may be `active` for a given branch. Never delete completed or
declined IDs; move them to History so old commits and discussions still make
sense.

## Ready

### SUN-011 — Local authenticated shared console broker

- **Status:** active
- **Owner:** Codex with Ryan Nelson
- **Branch:** `codex/sun-011-authenticated-console`
- **SPEC:** Section 15.2
- **Depends on:** SUN-001 and one validated live `console.sock`
- **Scope revision:** The former public OAuth deployment at
  `console.unix.wtf` is superseded by SUN-004. That origin is reserved for the
  static Tailcat SPA; SUN-011 retains the local broker and MCP-write policy.
- **Why:** Ryan and the MCP need a local out-of-band console that remains usable
  while guest networking is absent, with the human retaining unconditional
  input and an explicit persistent switch that can block MCP input.
- **Acceptance:** The app runs loopback-only on minnie against a local Unix
  socket or a fixed SSH console adapter; an xterm.js client can read and type;
  the MCP can read and conditionally type through an authenticated local
  control socket; the human's MCP-write block persists across browser and
  broker restarts; blocked MCP writes, reconnects, loopback enforcement, and
  the live QEMU console path are tested and documented.

### SUN-003 — Add the first live host trace recipe

- **Status:** ready
- **SPEC:** Sections 8.10, 8.11, and 15
- **Depends on:** SUN-001
- **Why:** Expose bounded host-side eBPF/perf evidence without a generic root
  shell.
- **Acceptance:** One named recipe is installed, privilege-checked, bounded,
  cleanup-tested, documented, and exercised against an exact QEMU PID.

### SUN-007 — Prove the cross-layer ioctl repair loop

- **Status:** ready
- **SPEC:** Sections 1–3 and 8
- **Depends on:** SUN-001 and the observability adapters required by the chosen
  failure
- **Why:** The project exists to locate and repair ambiguous failures that may
  belong to Solaris userland, illumos kernel code, an emulated guest driver,
  QEMU sun4v/device code, or lab wiring.
- **Acceptance:** One real failing ioctl (for example from `ifconfig`) is
  captured as competing hypotheses, observed at two or more layers, assigned
  to an owner by a discriminating test, patched, and rerun with the complete
  evidence history preserved.

### SUN-008 — Explain and fix one-visible-CPU SMP

- **Status:** ready
- **SPEC:** Sections 1–3 and 8
- **Depends on:** SUN-001
- **Why:** QEMU accepts a two-vCPU configuration, but the Solaris guest still
  reports one CPU. The failure may sit in QEMU creation, OpenBoot/sun4v machine
  description, Solaris enumeration and attach, interrupt topology, or bring-up.
- **Acceptance:** One investigation correlates configured and live QEMU vCPUs,
  firmware-described CPUs, Solaris discovery/attach state, debugger-visible CPU
  state, and host threads; a discriminating test identifies the missing layer,
  and the repair makes two CPUs visible or records a falsified assumption with
  sufficient evidence to choose the next owner.

## Ideas

### SUN-012 — SSH-reachable Unix socket consoles

- **Status:** idea
- **Why:** An operator should be able to register an exact byte-stream console
  socket on any host reachable through SSH. This covers QEMU and serial socket
  or named-pipe configurations from VirtualBox, VMware Fusion, and other VM
  managers without requiring hypervisor-specific discovery.
- **Question:** Which typed configuration and identity checks permit fixed
  remote sockets without turning the connector into arbitrary remote command
  execution or accepting stale sockets?
- **Promotion gate:** Define the host, socket-path, process-identity,
  allowlist, reconnect, timeout, and write-policy contracts; prove local and
  SSH-backed adapters against fake sockets; and validate one non-QEMU VM
  console without weakening the existing exact-target rules.

### SUN-013 — UTM interoperability on arbitrary Macs

- **Status:** idea
- **Depends on:** SUN-012 for UTM serial devices configured as Unix or TCP
  byte streams
- **Why:** Discover running UTM QEMU VMs, identify their serial modes, and
  expose attachable consoles without requiring a hand-written profile for each
  Mac.
- **Question:** Which UTM serial modes can be attached without restarting the
  VM or displacing UTM's CocoaSpice client, and should built-in terminal mode
  use a SPICE port helper or require an explicit socket configuration?
- **Promotion gate:** Define the UTM process, UUID, configuration, socket, and
  SPICE-port identity model; document the supported serial-mode matrix; and
  validate discovery, read, write, reconnect, and concurrent-client behavior
  against a disposable UTM VM.

### SUN-004 — Tailcat out-of-band console transport

- **Status:** ready
- **SPEC:** Sections 3 and 15.3
- **Design:** `docs/design-plans/2026-09-01-tailcat-console-transport.md`
- **Handoff:** `docs/design-plans/2026-09-04-new-delegate-tailcat-browser-console.md`
- **Plan:** `docs/plans/2026-09-01-tailcat-console-transport.md`
- **Depends on:** SUN-001
- **Why:** A user should be able to expose any serial-console Unix socket to a
  browser or MCP agent without opening an inbound port, enrolling in a tailnet,
  or sending console traffic through this project's web server.
- **Selected design:** A local Go helper gives one explicit Unix stream socket
  a fresh Tailcat address. A static page runs Tailcat in WebAssembly and joins
  that address directly through DERP. The MCP manages a bundled native Go
  client as a built-in console transport. The address is the session
  capability, one consumer may attach at a time, and the publisher supports
  explicit connect and listen socket modes.
- **Acceptance:** Fake-socket tests prove byte-exact bidirectional relay,
  single-browser ownership, reconnect after disconnect, fresh-address
  invalidation on exit, safe listen-socket cleanup, and bounded shutdown. A
  browser test proves xterm.js input and output through Tailcat WebAssembly
  without any console request reaching the static origin. MCP tests prove
  runtime attach, capability redaction, bounded reads, writes, detach, and
  child-process cleanup. A live test covers one QEMU or equivalent serial
  socket from both consumer paths. Shipped artifacts pin Tailcat, include
  required licenses, and document that browser traffic uses DERP and that the
  hosted relay has no stability or throughput guarantee. The tested static
  artifact is served at `https://console.unix.wtf/`, whose access logs contain
  only expected asset requests and no Tailcat identifier or console data.

### SUN-005 — Expand QMP support

- **Status:** idea
- **SPEC:** Section 15
- **Current boundary:** Typed `query-status` is available for QMP-backed runs,
  and debugger cleanup uses `stop` and `cont` internally. Arbitrary QMP
  execution is not exposed.
- **Question:** Which additional typed QMP queries materially improve evidence
  over HMP?
- **Promotion gate:** An allowlist and response schema are proposed for each
  additional command.

### SUN-006 — Guest-native DTrace recipes

- **Status:** idea
- **SPEC:** Sections 2, 3, and 10
- **Why:** Solaris has its own unusually powerful observability substrate. A
  guest-first debugger should use DTrace directly and correlate it with host
  eBPF/perf evidence without confusing their provenance.
- **Question:** Which initial named probes best discriminate boot, scheduler,
  syscall, interrupt, and network hypotheses on the target Solaris release?
- **Promotion gate:** Confirm available providers/privileges in the guest,
  define duration/output/cleanup contracts, and propose a named-recipe schema
  that cannot become an arbitrary privileged shell.

### SUN-009 — Content-addressed captures and analyzers

- **Status:** idea
- **Inspiration:** Joyent/Triton `manta-thoth`
- **Why:** Live observations should become durable subjects that can be
  re-examined without stopping the guest again. A successful one-off diagnosis
  should be promotable into a named analyzer and applied to later captures.
- **Question:** What is the smallest immutable capture bundle that preserves
  run identity, tool versions, raw evidence, extracted metadata, and lineage?
- **Promotion gate:** Define capture hashing, canonical storage, analyzer input
  and output contracts, provenance rules, and a single-capture-to-many-captures
  validation workflow.

### SUN-010 — Wedge, dump, hand off, replace

- **Status:** idea
- **SPEC:** Section 15.1
- **Depends on:** SUN-009 plus a validated VM lifecycle profile
- **Why:** A wedged VM should become a durable debugging case while a fresh VM
  starts booting. Offline diagnosis must not keep the lab's forward progress
  hostage.
- **Question:** Which QEMU-level dump captures enough Niagara state to resume
  useful debugger analysis, and which immutable inputs define a safe replacement?
- **Promotion gate:** Prove the dump format and offline debugger path; define
  the freeze, seal, verify, enqueue, launch, and rollback state machine; and
  test every interruption point without destroying the only recoverable run.

### SUN-014 — Agent-native serial terminal tools

- **Status:** idea
- **GTD:** `ryan/gtd#3671`
- **Depends on:** SUN-004
- **Why:** An agent harness should be able to operate a remote serial console as
  a stateful terminal even when the target cannot run a modern agent runtime or
  expose SSH. Targets include NextSTEP/m68k, Solaris/SPARC, network devices,
  firmware, installers, and bootloaders.
- **Selected direction:** Start with honest raw-terminal operations for attach,
  observe, send, wait, interrupt, and detach. Add command profiles later for
  environments that can prove stronger semantics, such as POSIX sentinel and
  exit-status framing, Cisco prompt and pager handling, or OpenBoot completion.
- **Question:** Which terminal state, cursor, history, timeout, mutation, and
  interruption contracts let an agent act effectively without pretending that
  every serial endpoint is Bash?
- **Promotion gate:** Define the stateful tool schemas, raw terminal model,
  interrupt semantics, output bounds, failure behavior, and fake-console test
  matrix. Specify the profile interface without implementing a profile in the
  raw-terminal milestone.

### SUN-015 — QEMU-native Tailcat console publishing

- **Status:** idea
- **GTD:** `ryan/gtd#3671`
- **Depends on:** SUN-004
- **Why:** QEMU could publish a fresh Tailcat console address as part of VM
  startup, binding the console transport to the VM lifecycle and eliminating a
  separate publisher command for QEMU users.
- **Question:** Should QEMU expose a Tailcat chardev backed by a managed sidecar,
  link a Go-built component, or leave the existing Unix-socket publisher as the
  integration boundary?
- **Promotion gate:** Compare QEMU chardev and lifecycle requirements, build and
  portability costs, capability disclosure, upstream acceptability, crash
  cleanup, and testability. Prototype the smallest viable integration without
  reimplementing Tailcat's Go data plane in C.

## History

### SUN-002 — Validate a live SPARC GDB capture profile

- **Status:** done
- **Completed:** 2026-08-27
- **Branch:** `codex/sun-002-live-sparc-gdb`
- **Validation:** `docs/live-validation/2026-08-27-sparc-gdb.md`
- **Outcome:** The installed MCP proved exact QEMU identity, used typed QMP
  status and cleanup over a private Unix socket, captured SPARC v9 registers
  and nearby instructions through a private GDB socket, detached, and proved
  the guest returned to `running`.

### SUN-001 — Implement the 0.1 MCP core

- **Status:** done
- **Completed:** 2026-08-27
- **Commit:** `eeec522` plus final conformance follow-up
- **Plan:** `docs/plans/2026-08-27-initial-mcp.md`
- **Outcome:** Portable stdio server, safety adapters, evidence ledger,
  contributor workflow, documentation, packaging, and fake-backed conformance
  suite implemented. Live host/guest profiles remain separately tracked.
