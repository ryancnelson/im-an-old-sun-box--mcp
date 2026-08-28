# Test requirements

| Acceptance requirement | Automated coverage | Live coverage |
| --- | --- | --- |
| Cursor-preserving transcript | `tests/test_console_broker.py` | MCP read after browser output |
| Human-priority input | `tests/test_console_broker.py` | Human Ctrl-C during queued MCP input |
| Persistent fail-closed policy | `tests/test_console_broker.py` | Checkbox plus broker restart |
| Bearer-authenticated RPC | `tests/test_console_rpc.py` | MCP status and write |
| Lease lifecycle and expiry | `tests/test_console_rpc.py` | Acquire, write, release |
| GitHub ID allowlist | `tests/test_console_web.py` | Login as `ryancnelson` |
| Authenticated WebSocket | `tests/test_console_web.py` | Browser terminal session |
| Tribblix PID verification | `tests/test_runs.py` | `qemu.status` on `ec2trib` |
| Browser assets in wheel | `tests/test_packaging.py` | Console page without CDN access |
| Existing MCP behavior | Full `pytest` suite | Existing live smoke checks |

No automated test requires a live VM, GitHub credentials, Doppler credentials,
root, or guest networking.
