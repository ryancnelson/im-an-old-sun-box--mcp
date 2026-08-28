# Phase 1: broker core

## Tasks

1. Add fake-console tests for transcript cursors, reconnect state, bounded
   input, and human-priority ordering.
2. Add policy tests for default state, atomic persistence, restart survival,
   and fail-closed malformed input.
3. Implement `ConsoleTranscript`, `ConsolePolicyStore`, and `ConsoleBroker` in
   `src/old_sun_mcp/console_broker.py`.
4. Verify with:

   ```bash
   uv run pytest -q tests/test_console_broker.py
   ```

## Done when

The broker can own a fake Unix console, broadcast bytes, queue human and MCP
input with the required priority, and preserve policy across instances.
