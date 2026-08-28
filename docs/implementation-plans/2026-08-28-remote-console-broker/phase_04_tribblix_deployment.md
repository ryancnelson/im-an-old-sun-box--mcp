# Phase 4: Tribblix deployment

## Tasks

1. Add an `ec2trib` configuration example for `/tink/runs`, QMP, broker RPC,
   transcript, and persistent policy paths.
2. Add nginx and SMF templates that contain no secrets or dated run paths.
3. Add an operator command that resolves `/tink/runs/oi-basecamp-latest` once
   and starts the broker for that exact run.
4. Add a live smoke procedure covering browser input, MCP read/write, policy
   persistence, QMP status, and disconnect behavior.
5. Install the project in a dedicated Python virtual environment on `ec2trib`.
6. Attach the broker to the running `oi-basecamp` console and run the live
   checks without rebooting QEMU.

## Done when

The broker owns the live serial socket, artifacts remain run-scoped, and both
human and MCP clients pass the acceptance checks.
