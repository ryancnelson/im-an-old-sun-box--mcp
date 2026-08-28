# Remote console broker and web client

**Status:** approved for implementation

**Date:** 2026-08-28

## Purpose

Give a human operator and the MCP agent simultaneous, out-of-band access to a
running Niagara serial console. One broker owns QEMU's Unix serial socket.
Browser and MCP clients use the broker instead of competing for the QEMU
socket.

The first integration target is the live `oi-basecamp` run on `ec2trib`:

```text
/tink/runs/oi-basecamp-20260828T081743Z-31482
```

Guest networking is outside the control path.

## Decisions already made

- Human keyboard input is always accepted.
- Human input takes priority over queued MCP input.
- An authenticated human can check a box that blocks MCP writes.
- The block survives browser disconnects, broker restarts, and VM restarts.
- MCP reads remain available while writes are blocked.
- A blocked MCP write returns the policy state instead of pretending that the
  bytes were sent.
- Browser authentication uses GitHub OAuth and admits only the configured
  numeric GitHub account ID for `ryancnelson`.
- MCP authentication uses a scoped bearer token supplied through Doppler.
- The broker owns a transcript with stable byte cursors and an audit record for
  input.

## Considered approaches

### Browser connects to QEMU

An HTTP server could proxy one browser directly to `console.sock`. MCP would
then need another reader or would have to steal the browser connection. QEMU's
serial socket has one consumer, so this cannot provide reliable shared access.

### Separate browser and MCP proxies

Two proxy processes could race for the QEMU socket. This breaks transcript
ordering and makes a write lock advisory. It also leaves no process able to
state which bytes reached QEMU.

### One console broker

The broker is QEMU's sole serial client. It fans output to browsers and MCP,
serializes all input, persists policy, and assigns transcript cursors. This is
the selected design.

## Components

```text
QEMU console.sock
       |
       | one Unix-socket connection
       v
console broker
  |-- transcript file and cursor index
  |-- persistent MCP-write policy
  |-- human-priority input queue
  |-- authenticated WebSocket/HTTP server
  `-- bearer-authenticated Unix RPC socket
             |
             v
       old-sun MCP tools
```

The broker and web server run in one Python process. The HTTP listener binds to
loopback. nginx terminates TLS and forwards HTTP and WebSocket traffic. The MCP
server reaches the broker through a private Unix RPC socket.

## Broker lifecycle

The broker receives an exact run directory and derives `console.sock` only
after containment validation. It connects with bounded retry because QEMU and
the broker may start in either order. A disconnect marks the console offline,
preserves clients and cursors, and begins retrying. It never starts or kills
QEMU.

Every byte read from QEMU is appended to a run-local binary transcript before
it is published to clients. The transcript file size is the next cursor, so a
broker restart resumes cursor numbering without a database.

The broker writes input in bounded chunks through one coroutine. Human input
has queue priority `0`; MCP input has priority `10`. Queue sequence numbers
preserve order within each source class. An MCP chunk is capped so a large
agent write cannot delay a human Ctrl-C behind the entire payload.

## Persistent policy

The policy file lives outside a run directory, for example:

```text
/tink/vm-state/oi-basecamp/console-policy.json
```

It records `mcp_write_enabled`, the authenticated GitHub ID and login that last
changed it, and an update timestamp. Updates use write-fsync-rename. Missing
policy starts with MCP writes enabled. Malformed, unreadable, or invalid policy
fails closed and reports the error to clients. Only an authenticated human HTTP
request can change the policy.

The browser checkbox is labelled `Block MCP keyboard input`. Checked means MCP
writes are disabled. Console reads and `expect` continue to work.

## MCP RPC

The broker RPC uses one JSON object per line over a mode-0600 Unix socket. Each
request contains a bearer token, request ID, method, and parameters. Requests
and responses are size-bounded. Token comparison uses a constant-time check.

Methods:

| Method | Effect |
| --- | --- |
| `status` | Return connection, cursor, policy, human-client, and lease state |
| `read` | Return bytes after a cursor, with gap and next-cursor metadata |
| `acquire` | Create one expiring MCP writer lease |
| `write` | Queue bounded bytes under the active lease |
| `send_key` | Queue a reviewed key such as Ctrl-C, Enter, Escape, or Tab |
| `expect` | Wait for a byte or UTF-8 pattern after a cursor |
| `release` | Release the caller's lease |

The lease serializes MCP clients. It does not exclude human input. Leases expire
and are lost on broker restart. The policy check occurs when a write is queued,
not only when a lease is acquired.

## MCP tools

The MCP server exposes the RPC methods as:

- `console.status`
- `console.read`
- `console.acquire`
- `console.write`
- `console.send_key`
- `console.expect`
- `console.release`

All results use the existing evidence envelope. Reads identify the broker RPC
socket as their source. Writes require a non-empty reason and return
`mutation=disruptive`. Authentication tokens never appear in envelopes or
logs.

## Web authentication

`/login` starts GitHub's OAuth authorization-code flow. The callback exchanges
the code and reads `GET /user`. Admission requires the configured numeric ID
and a case-insensitive login match for `ryancnelson`. The numeric ID is the
stable authority; the login check detects configuration mistakes.

Browser sessions are short-lived HMAC-signed cookies with `Secure`,
`HttpOnly`, and `SameSite=Lax`. OAuth state is signed and expires. State-changing
HTTP requests require an authenticated session and a matching origin. The
WebSocket validates the same session before accepting.

Secrets arrive through environment variables populated by Doppler:

- `OLD_SUN_GITHUB_CLIENT_ID`
- `OLD_SUN_GITHUB_CLIENT_SECRET`
- `OLD_SUN_SESSION_SECRET`
- `OLD_SUN_CONSOLE_MCP_TOKEN`

## Browser client

The application serves pinned xterm.js assets locally. It does not depend on a
CDN or Node on `ec2trib`. On connection it receives recent transcript bytes,
the current cursor, console status, and policy. Terminal keyboard data is sent
as base64 WebSocket messages. Console output uses the same binary-safe form.

The page shows:

- connection state and run name;
- the xterm.js terminal;
- the persistent MCP-write checkbox;
- current MCP lease information; and
- the authenticated GitHub login.

## Failure behavior

- QEMU socket loss leaves the web and RPC servers available with
  `console_connected=false`.
- Broker RPC authentication failure returns a generic unauthorized error.
- Policy parse or persistence failure blocks MCP writes.
- Transcript failure stops console reads and writes rather than losing audit
  ordering.
- Browser disconnect does not alter policy or release an MCP lease.
- MCP disconnect does not release a lease; explicit release or expiry does.
- The broker never buffers an unbounded console history or input payload.

## Delivery phases

1. Broker core, transcript cursors, persistent policy, input priority, and
   fake-console tests.
2. Authenticated RPC server/client and console MCP tools.
3. GitHub-authenticated web server and xterm.js client.
4. Tribblix process compatibility, configuration, packaging, and operations.
5. Live deployment against `oi-basecamp`, followed by nginx and SMF setup.

## Acceptance criteria

- A fake QEMU socket proves output fanout, cursor reads, reconnect, and bounded
  transcript behavior.
- A queued human Ctrl-C is written before queued MCP data that has not begun
  writing.
- The human block persists across a new broker instance and rejects MCP writes
  while allowing `status`, `read`, and `expect`.
- RPC rejects missing or incorrect bearer tokens without logging them.
- MCP tools return typed envelopes for offline console, blocked write, expired
  lease, timeout, and successful input.
- OAuth tests reject the wrong GitHub ID even when the login text matches.
- The browser can type at the live OpenBoot prompt and observe its response.
- MCP can read the same transcript, acquire a lease, type a harmless OpenBoot
  command, and release the lease.
- Checking the browser lock immediately prevents the next MCP write and remains
  checked after broker restart.
- Existing MCP tests remain green.
