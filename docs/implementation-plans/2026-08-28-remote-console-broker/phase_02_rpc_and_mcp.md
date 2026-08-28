# Phase 2: RPC and MCP tools

**Status:** complete

## Tasks

1. Add authenticated JSON-lines RPC tests for status, read, lease lifecycle,
   blocked writes, keys, expect, malformed requests, and size limits.
2. Implement the broker RPC server and synchronous MCP client in
   `src/old_sun_mcp/console_rpc.py`.
3. Extend strict TOML configuration with the broker socket and bearer-token
   environment-variable name.
4. Add the seven `console.*` service methods and MCP registrations.
5. Fix exact process command-line inspection on Tribblix by using `pargs -l`
   when Linux-style `ps -o command=` is unavailable.
6. Verify with:

   ```bash
   uv run pytest -q tests/test_console_rpc.py tests/test_config.py \
       tests/test_runs.py tests/test_service.py tests/test_server.py
   ```

## Done when

An MCP client can use every console method through a bearer-authenticated Unix
socket, and live-run PID verification works on Linux and Tribblix.
