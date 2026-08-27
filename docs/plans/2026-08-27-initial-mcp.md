# Initial MCP Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Ship the safe, testable 0.1 core described by `SPEC.md`, together with a contribution workflow that keeps ideas, work, and documentation organized.

**Architecture:** A Python 3.11 package exposes an MCP stdio server over small service modules. Inputs resolve through strict configuration and validated run identities; every operation returns one common evidence envelope. Unix-socket and subprocess integrations sit behind bounded adapters so fake servers and executables can prove behavior without a live VM.

**Tech Stack:** Python 3.11+, official `mcp` Python SDK, `tomllib`, `pytest`, Unix sockets, JSON Lines, SHA-256, advisory file locking.

---

### Task 1: Establish workflow and packaging

**Files:** Create `JOINING-AND-CONTRIBUTING.md`, `TODO.md`, `pyproject.toml`, `src/old_sun_mcp/__init__.py`, `src/old_sun_mcp/__main__.py`, `tests/test_packaging.py`; modify `README.md`.

1. Write a failing test that imports the package, checks its version, and imports the entry-point module.
2. Run `python3 -m pytest tests/test_packaging.py -q` and confirm failure.
3. Add package metadata and the `old-sun-mcp` entry point.
4. Make `TODO.md` the sole canonical backlog, with stable IDs, status, SPEC linkage, acceptance criteria, and closeout rules.
5. Document the idea → TODO → `codex/<todo-id>-<slug>` branch → tests/docs → PR → closeout workflow.
6. Link SPEC, TODO, plan, and contributor guide from README, distinguishing implemented and planned work.
7. Re-run the focused test and confirm it passes.

### Task 2: Envelopes, errors, and strict configuration

**Files:** Create `src/old_sun_mcp/errors.py`, `envelope.py`, `config.py`, `examples/config.toml`, `tests/test_envelope.py`, and `tests/test_config.py`.

1. Write failing tests for UTC envelopes, structured errors, truncation, config search order, safe missing config, unknown keys, and adapter/recipe parsing.
2. Implement strict immutable config models, stable errors, byte-aware truncation, and success/failure envelopes.
3. Add a portable example with no secrets or private paths.
4. Run `python3 -m pytest tests/test_envelope.py tests/test_config.py -q`.

### Task 3: Safe run discovery and exact process identity

**Files:** Create `src/old_sun_mcp/runs.py` and `tests/test_runs.py`.

1. Write failing tests for discovery, ambiguous names, containment, symlink escapes, PID errors, exact command-line evidence, manifest redaction, and capabilities.
2. Implement canonical selection, metadata discovery, sanitization, and exact PID verification.
3. Run `python3 -m pytest tests/test_runs.py -q`.

### Task 4: Bounded guest and QEMU adapters

**Files:** Create `src/old_sun_mcp/guest.py`, `hmp.py`, `tests/test_guest.py`, and `tests/test_hmp.py`.

1. Write fake-backed failing tests for console tails, argv integrity, exit status, timeouts, HMP framing, allowlists, control classification, and socket failures.
2. Implement bounded console reads, configured guest adapters with `shell=False`, serialized HMP requests, and explicit allowlists.
3. Run `python3 -m pytest tests/test_guest.py tests/test_hmp.py -q`.

### Task 5: Host samples and named trace recipes

**Files:** Create `src/old_sun_mcp/host.py` and `tests/test_host.py`.

1. Write failing tests for exact-PID deltas, capability absence, duration bounds, literal PID substitution, privilege errors, timeout, and cleanup.
2. Implement platform-tolerant sampling/capability probes and bounded recipe execution with guaranteed teardown.
3. Run `python3 -m pytest tests/test_host.py -q`.

### Task 6: Immutable evidence and hypothesis ledger

**Files:** Create `src/old_sun_mcp/ledger.py` and `tests/test_ledger.py`.

1. Write failing tests for canonical digests, locking, append-only ordering, filtering, corruption, required predictions/tests, and transitions.
2. Implement locked JSONL events, stable IDs/digests, reads, evidence validation, and hypothesis updates without overwrites.
3. Run `python3 -m pytest tests/test_ledger.py -q`.

### Task 7: Debugger cleanup orchestration

**Files:** Create `src/old_sun_mcp/debugger.py` and `tests/test_debugger.py`.

1. Write fake-backed failing tests proving cleanup on success, timeout, malformed output, and debugger failure.
2. Implement profile-driven GDB execution and monitor orchestration behind injectable adapters.
3. Always attempt detach/resume and verify post-status; return `CLEANUP_UNPROVED` when proof is unavailable.
4. Run `python3 -m pytest tests/test_debugger.py -q`.

### Task 8: MCP service and stdio server

**Files:** Create `src/old_sun_mcp/service.py`, `server.py`, `tests/test_service.py`, and `tests/test_server.py`.

1. Write failing service tests for every Section 15 operation and a stdio initialization/tool-enumeration smoke test.
2. Implement a façade that turns domain errors into envelopes and logs safe metadata to stderr.
3. Register canonical tools with mutation annotations and guest-first initialization instructions.
4. Run `python3 -m pytest tests/test_service.py tests/test_server.py -q`.

### Task 9: Operations documentation and conformance

**Files:** Create `docs/OPERATIONS.md`, `docs/LIVE-SMOKE-TEST.md`, `docs/CODEX-CONFIG.md`; modify `README.md` and `TODO.md`.

1. Document installation, configuration, privileges, launch, safe failures, an opt-in non-destructive live smoke test, and Codex MCP configuration.
2. Update implementation status and close completed TODOs while retaining a concise history.
3. Run `python3 -m pytest -q`, `python3 -m build`, and `git diff --check`.
4. Inspect tracked files and secret-like strings; leave no children, sockets, or mutated fixtures.
5. Commit and publish only after all checks pass.
