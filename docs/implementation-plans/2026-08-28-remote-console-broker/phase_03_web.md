# Phase 3: authenticated web client

## Tasks

1. Add session-signing and GitHub OAuth admission tests with a fake OAuth
   client.
2. Implement the FastAPI application, OAuth routes, policy endpoint, and
   authenticated console WebSocket in `src/old_sun_mcp/console_web.py`.
3. Add a Python entry point that starts the broker and ASGI server together.
4. Vendor pinned xterm.js and fit-addon assets. Add the terminal HTML,
   stylesheet, and browser module under `src/old_sun_mcp/static/`.
5. Add package-data declarations and dependency pins.
6. Verify with:

   ```bash
   uv run pytest -q tests/test_console_web.py tests/test_packaging.py
   uv build
   ```

## Done when

Only the configured GitHub identity can load the console page, WebSocket, and
policy endpoint, and the built wheel contains every browser asset.
