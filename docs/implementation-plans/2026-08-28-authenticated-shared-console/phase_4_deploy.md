# Phase 4: ec2trib deployment

> **Superseded (2026-09-01):** Do not execute this public deployment phase.
> `console.unix.wtf` will host the static Tailcat SPA described in
> `docs/design-plans/2026-09-01-tailcat-console-transport.md`. Keep the shared
> broker loopback-only unless a later design assigns it another origin.

Build a pinned Caddy release natively on illumos, install broker and Caddy SMF
manifests, supply secrets outside Git, and bind the broker to loopback. Test
locally before opening AWS ports 80 and 443. Register the GitHub OAuth callback,
then verify TLS, OAuth denial, authorized WebSocket access, console input, and
persistent MCP blocking.

Verification: repository live-test runbook plus captured command results.
