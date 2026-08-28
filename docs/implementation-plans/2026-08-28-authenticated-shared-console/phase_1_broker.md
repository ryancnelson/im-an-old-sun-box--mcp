# Phase 1: broker core

Write failing tests for persistent operator state, bounded history, local QEMU
socket and fixed argv/SSH transport reconnects, serialized human writes, and
blocked MCP writes. Implement the broker and local control protocol until
those tests pass.

Verification: `pytest tests/test_console_state.py tests/test_console_broker.py tests/test_console_control.py`
