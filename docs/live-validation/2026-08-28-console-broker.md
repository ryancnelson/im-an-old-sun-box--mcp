# Live console broker validation on ec2trib

**Date:** 2026-08-28

**Run:** `oi-basecamp-20260828T081743Z-31482`

**Host:** Tribblix x86 in EC2, known locally as `ec2trib`

## Scope

This check used the QEMU serial socket at `console.sock` while the guest was at
the OpenBoot `ok` prompt. It did not reboot QEMU, modify a disk, or depend on
guest networking.

The Python 3.13 virtual environment at `/opt/old-sun-console/venv` installed the
wheel's `console` extra. The dependency set contained Starlette, Uvicorn,
HTTPX, and their pure-Python dependencies. It did not install the MCP SDK,
Pydantic, `pydantic-core`, or a Rust toolchain.

## Authenticated RPC check

A one-use bearer token existed only in the smoke-test process. The broker:

1. connected as the sole client of the QEMU serial socket;
2. started its mode-0600 JSON-lines RPC socket;
3. authenticated an RPC client;
4. granted a 15-second MCP writer lease;
5. queued the read-only OpenBoot command `printenv auto-boot?`;
6. matched the next `ok` prompt after the pre-command cursor;
7. returned the transcript bytes through RPC;
8. released the lease; and
9. detached without stopping QEMU.

Observed transcript:

```text
printenv auto-boot?
auto-boot? =            false
ok
```

The default policy reported MCP writes enabled. The command audit recorded the
input length and SHA-256 digest, not the input bytes or bearer token.

## Installed web entry-point check

The installed `old-sun-console` entry point started Uvicorn on a temporary
loopback port with smoke-only credentials. Its lifespan started the same broker
and RPC server. `GET /healthz` returned:

```json
{
  "ok": true,
  "console_connected": true
}
```

SIGTERM produced a clean application shutdown and detached the console broker.
QEMU remained running.

## Not yet proved

- GitHub OAuth through a real HTTPS callback
- admission restricted to Ryan's GitHub account in the deployed service
- browser keyboard and xterm.js rendering against the live console
- checkbox persistence through an actual broker restart
- nginx WebSocket forwarding and the SMF service manifest
- MCP access from Codex through a permanent broker token

Those checks require a public hostname, TLS, a GitHub OAuth application, and
write-capable secret provisioning. None was invented or committed for this
smoke test.
