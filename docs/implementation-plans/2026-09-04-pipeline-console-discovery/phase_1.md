# SUN-016 implementation

Goal: populate the running local console menus with native and containerized
pipeline guests, preserving the future static SPA/Tailcat boundary.

1. Add failing discovery tests in tests/test_console_containers.py for trusted
   prefix/root configuration, exact instance identity, socket validation,
   container restart, provider failure isolation and connector quoting.
   Run `.venv/bin/pytest -q tests/test_console_containers.py` and record RED.
2. Implement a bounded, read-only remote Docker inventory helper and integrate
   typed container targets into console_discovery.py. Reuse process/serial
   parsing. Return structured records without environment variables or secrets.
   Run the new tests and existing discovery/target/web tests for GREEN.
3. Add failing reconnect tests, then revalidate the selected instance on every
   connection. Add container metadata to the common HTTP/MCP target payload.
4. Add browser behavior tests using Node's built-in test runner and a small fake
   DOM. Implement non-overlapping periodic refresh, preserved selection and
   deduplicated errors. Run those tests and the Python suite.
5. Update the registry from checked-in Woodpecker paths and container naming
   conventions. Test the registry and document the provider boundary.
6. Commit after full tests. Install/restart the localhost:8877 console from the
   standalone repository using its existing tmux service environment. Verify
   authenticated discovery and browser menus without writing to guest consoles.
   Preserve the existing operator state and credentials.

SUN-017 encrypted invitations depend on the separate browser key-unlock decision;
do not block SUN-016 on it or report encrypted links as shipped.
