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

### SUN-002 — Validate a live SPARC GDB capture profile

- **Status:** ready
- **SPEC:** Sections 8.12 and 15
- **Depends on:** SUN-001
- **Why:** Fake-backed cleanup proves orchestration, but the actual toolchain and
  target profile must be validated on the VM host.
- **Acceptance:** A documented non-destructive live capture records registers
  and nearby instructions, proves detach/resume, and leaves QEMU running.

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

### SUN-004 — Cross-host out-of-band relay

- **Status:** idea
- **SPEC:** Sections 3 and 15
- **Question:** Which transport preserves local tool contracts while remaining
  independent of guest networking?
- **Promotion gate:** Threat model, authentication, transport choice, and a
  failure/cleanup contract are written down.

### SUN-005 — QMP support

- **Status:** idea
- **SPEC:** Section 15
- **Question:** Which typed QMP queries materially improve evidence over HMP?
- **Promotion gate:** Initial command allowlist and schemas are proposed.

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

## History

### SUN-001 — Implement the 0.1 MCP core

- **Status:** done
- **Completed:** 2026-08-27
- **Commit:** `eeec522` plus final conformance follow-up
- **Plan:** `docs/plans/2026-08-27-initial-mcp.md`
- **Outcome:** Portable stdio server, safety adapters, evidence ledger,
  contributor workflow, documentation, packaging, and fake-backed conformance
  suite implemented. Live host/guest profiles remain separately tracked.
