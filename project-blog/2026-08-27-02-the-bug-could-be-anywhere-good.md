# The bug could be anywhere

*August 27, 2026*

Solaris `ifconfig` barfs on weird ioctls.

## `ifconfig` and the ioctl

The failure could belong to several components:

- the assumptions made by `ifconfig`;
- the illumos networking stack;
- my Solaris driver for the emulated device;
- QEMU's device implementation; or
- the lab configuration connecting them.

The MCP gives me one investigation record across those components. I can
reproduce the ioctl failure, preserve competing ownership hypotheses, observe
the syscall and kernel path with DTrace, inspect driver and CPU state, compare
the corresponding QEMU and host activity, patch the implicated component, and
run the same test again.

DTrace reports what Solaris is doing. Host eBPF and perf report what the QEMU
process is doing. The evidence ledger records those observations with different
layer provenance even when their timestamps describe the same event.

## SMP enumeration

QEMU accepts a two-vCPU configuration, but this Solaris guest reports one CPU.
The next investigation needs to compare:

- QEMU's configured and live vCPU inventory;
- the CPUs described by OpenBoot and the sun4v machine description;
- Solaris CPU enumeration, attachment, and scheduler state;
- SPARC registers and execution state through GDB; and
- exact-QEMU-PID host thread activity.

Those observations should show whether the missing CPU disappears during QEMU
creation, firmware description, Solaris enumeration, interrupt setup, or CPU
bring-up. The repair can then be tested against the same inventory.
