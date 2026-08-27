# Live SPARC GDB profile

## Problem

The 0.1 server has tested debugger cleanup orchestration, but it cannot run a
debugger. The Niagara lab also uses `manifest.env` and `replay.log`, while the
portable defaults are `run.manifest` and `console.log`.

## Design

Keep machine-specific paths in TOML. A run root may name its manifest and
console log. A named debugger profile selects a fixed SPARC architecture, a
loopback endpoint, and a timeout. The GDB executable remains an explicit path.

For older runs, the adapter starts the QEMU stub through that run's HMP socket.
For newer runs, it uses the preconfigured private Unix GDB socket and QMP for
typed status and cleanup control. It launches GDB without init files and
collects registers, instructions at the PC, and a best-effort backtrace. Users
cannot supply GDB commands through the MCP call.

Cleanup has two independent parts: the bounded GDB child must exit, which
closes its remote connection, and QEMU must return to its recorded pre-capture
state. Failure to prove the latter returns `CLEANUP_UNPROVED`.

## Safety constraints

- A TCP endpoint must be IPv4 loopback. A Unix endpoint must be a safe relative
  path inside the resolved run.
- Architectures are limited to `sparc` and `sparc:v9`; endian mode is fixed to
  big-endian.
- Output and execution time remain bounded by server configuration.
- PID identity is proved before monitor or debugger access.
- The capture API accepts a profile name, not arbitrary debugger commands.

## Acceptance

Unit tests cover parsing, bounded GDB execution, malformed capture output,
debugger failure, and state restoration. The live smoke test must use the exact
Niagara run PID, capture registers and nearby instructions, and show QEMU
running after detach.

The structured result is deliberately suitable for a later Thoth-style layer:
immutable, content-addressed captures with metadata enrichment by named
analyzers. That storage and analyzer lifecycle is tracked separately as
SUN-009; live debugger validation does not depend on it.

Live validation completed on 2026-08-27. See
`docs/live-validation/2026-08-27-sparc-gdb.md`.
