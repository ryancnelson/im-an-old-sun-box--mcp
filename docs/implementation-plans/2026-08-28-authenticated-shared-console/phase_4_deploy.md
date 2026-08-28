# Phase 4: ec2trib deployment

Build a pinned Caddy release natively on illumos, install broker and Caddy SMF
manifests, supply secrets outside Git, and bind the broker to loopback. Test
locally before opening AWS ports 80 and 443. Register the GitHub OAuth callback,
then verify TLS, OAuth denial, authorized WebSocket access, console input, and
persistent MCP blocking.

Verification: repository live-test runbook plus captured command results.
