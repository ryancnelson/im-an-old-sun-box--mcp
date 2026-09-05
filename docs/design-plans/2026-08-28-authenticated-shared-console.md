# Authenticated shared console

> **Deployment decision (2026-09-01):** The public deployment described here
> is superseded by the static Tailcat design in
> `2026-09-01-tailcat-console-transport.md`. `console.unix.wtf` is reserved for
> that SPA. This document still governs the loopback broker, local MCP control
> socket, and persistent MCP-write block.

## Goal

Give Ryan and the local MCP a shared, loopback-only QEMU serial console without
making guest networking part of the control plane.

## Selected design

For local use, the Python service binds only to loopback and does not need a
public proxy. The superseded public design placed Caddy in front of it for TLS
and used GitHub OAuth pinned to a login and immutable numeric user ID; those
parts are retained here as historical constraints, not the current deployment
target.

One broker owns the console transport. The transport is either a local QEMU
Unix socket or a fixed argv adapter for an SSH-accessible host. Browser clients
receive bounded history plus live bytes through WebSockets. Authenticated human
browser input is always eligible to reach the console. MCP clients use an
NDJSON protocol on a mode-restricted local Unix control socket.

The operator control is stored as `mcp_write_blocked`, defaults to `true`, and
is replaced atomically on disk. The UI checkbox changes that state. MCP reads
remain available while writes are blocked, and every MCP response reports the
state.

## Rejected alternatives

- nginx plus Certbot keeps the installed native nginx but adds a separate ACME
  client and renewal hook. The installed nginx build lacks its upstream ACME
  module. Caddy removes that integration work.
- A browser connection directly to QEMU cannot perform OAuth, cannot arbitrate
  writers, and would compete for the serial socket.
- A GitHub-login-only allowlist is vulnerable to account renaming and future
  reuse. The broker pins login and numeric ID.

## Components

- `old_sun_console.auth`: OAuth state, token exchange, identity verification,
  and secure sessions.
- `old_sun_console.state`: atomic persistent operator state.
- `old_sun_console.broker`: QEMU socket ownership, bounded history, broadcast,
  serialized writes, and reconnects.
- `old_sun_console.transport`: local Unix and fixed argv/SSH console streams.
- `old_sun_console.control`: authenticated local NDJSON API for MCP.
- `old_sun_console.web`: login, callback, UI, state endpoint, and WebSocket.
- MCP tools `guest.console_status`, `guest.console_read`, and
  `guest.console_write` use the local control socket.
- SMF manifests run Caddy and the broker with persistent data directories.

## Security properties

- No console content is returned before OAuth authorization.
- OAuth callback state is checked and consumed once.
- Cookies are `Secure`, `HttpOnly`, and `SameSite=Lax`.
- Production startup fails if OAuth, session, identity-pin, or MCP-token
  configuration is absent.
- OAuth bypass is accepted only on an explicit IP loopback bind for local
  development on minnie.
- The web service listens only on `127.0.0.1`.
- The control socket and state files are not world-readable.
- MCP writes are checked immediately before the serialized socket write.
- Secrets are supplied through environment variables and are never logged.

## Failure behavior

- Lost QEMU socket: clients stay connected, receive disconnected state, and
  the broker retries with bounded backoff.
- Lost browser: the persistent MCP-write block is unchanged.
- Broker restart: state is reloaded before accepting clients.
- OAuth or GitHub API failure: login fails closed.
- Caddy certificate failure: the broker remains loopback-only.
- Blocked MCP write: zero bytes are sent and the response identifies the
  operator block.

## Acceptance criteria

- Unit tests prove OAuth allow and deny paths, state persistence, atomic state
  updates, bounded history, browser-versus-MCP write policy, control-token
  rejection, and reconnect behavior with fake Unix sockets.
- MCP enumeration and fake-control-socket tests cover all new tools.
- A live test proves browser output and input against the selected QEMU run.
- External tests prove HTTPS, OAuth redirect, unlisted-user denial, and
  WebSocket upgrade behavior.
- A broker restart preserves the MCP-write block.
