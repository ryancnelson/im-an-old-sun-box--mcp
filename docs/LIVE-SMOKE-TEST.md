# Opt-in Live Smoke Test

This procedure is observational except for append-only evidence records. It is
not part of the automated test suite.

## Preconditions

- Use a disposable or already snapshotted lab run.
- Confirm `qemu.pid`, `monitor.sock`, and `console.log` belong to that run.
- Start with no debugger attached and record whether QEMU is running or paused.
- Configure one run root and `ledger_dir`; do not configure a privileged trace
  recipe for this smoke test.

## Procedure

1. Start `old-sun-mcp` through an MCP client.
2. Call `lab.list_runs(include_stopped=true)` and confirm the intended run is
   unique.
3. Call `lab.describe_run` and verify PID identity is proved without exposing
   manifest secrets.
4. Call `guest.console_tail` and record one sourced guest observation.
5. Call `qemu.status` and confirm HMP reports the expected pre-state.
6. Call `host.process_sample` for one second and treat host activity only as
   host-layer evidence.
7. Start two competing hypotheses, record the guest/QEMU/host observations,
   weaken or falsify one, and read the immutable history.
8. Call `qemu.status` again. Confirm the VM state is unchanged and no debugger,
   trace process, child process, or extra Unix socket remains.

Do not call guest execution, HMP control, debugger capture, or host trace as
part of this smoke test.

