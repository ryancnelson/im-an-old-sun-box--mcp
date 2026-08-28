# Test requirements

| Requirement | Automated test | Live verification |
|---|---|---|
| OAuth allows only pinned Ryan identity | `test_console_auth.py` | GitHub login |
| No unauthenticated console disclosure | `test_console_web.py` | HTTP and WebSocket |
| Human can always type | `test_console_broker.py` | guest echo |
| MCP block defaults on and persists | `test_console_state.py` | broker restart |
| Blocked MCP write sends no bytes | `test_console_broker.py` | MCP tool call |
| MCP authenticates locally | `test_console_control.py` | live MCP status |
| Broker reconnects and bounds history | `test_console_broker.py` | socket reconnect |
| Minnie can use local or SSH-backed transport | `test_console_transport.py` | loopback browser |
| Managed TLS and WebSocket proxy | configuration test | external HTTPS |
