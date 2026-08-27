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

### SUN-001 — Implement the 0.1 MCP core

- **Status:** active
- **Branch:** `main` (bootstrap exception; subsequent work uses feature branches)
- **SPEC:** Sections 5–15
- **Plan:** `docs/plans/2026-08-27-initial-mcp.md`
- **Why:** Turn the normative contract into a safe, testable stdio MCP server.
- **Acceptance:** All Section 15 capabilities and Section 14 conformance tests
  pass without a live VM, root access, or networking.

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

## History

No completed items yet.

