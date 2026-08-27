# The Bug Could Be Anywhere. Good.

*August 27, 2026*

Once the README and SPEC existed, two examples made the actual product much
clearer.

The first was mundane in exactly the right way: Solaris `ifconfig` barfs on
weird ioctls.

That symptom does not arrive with a helpful label saying where the fix belongs.
Maybe an old userland utility is making an assumption that this environment
violates. Maybe the illumos networking stack mishandles the request. Maybe the
Solaris device driver for the emulated hardware returns the wrong shape or
error. Maybe QEMU's device model does not implement a register or transition
correctly. Maybe the lab connected the pieces incorrectly.

Before this MCP, it was too easy for each layer to become somebody else's
problem. With the MCP, the ambiguity becomes an investigation plan. Reproduce
the ioctl failure. Preserve competing ownership hypotheses. Observe the syscall
and kernel path with guest-native DTrace. Inspect driver and CPU state. Compare
what the emulated device did through QEMU and host tracing. Patch the layer that
a discriminating test actually implicates. Then rerun the same evidence set.

DTrace matters here. It is not a cute historical checkbox underneath modern
host eBPF. DTrace is Solaris explaining itself in its native tongue. Host eBPF
and perf explain the QEMU process. Those are complementary x-ray angles, and
their provenance must stay distinct even when they line up across the virtual
hardware boundary.

The second example was SMP. Other people working on this stack report that SMP
is possible, but asking QEMU for two CPUs still leaves this Solaris guest seeing
one.

Again, “SMP is broken” is only the symptom. Did QEMU really instantiate both
vCPUs? Did OpenBoot or the sun4v machine description advertise them? Did
Solaris enumerate both but fail to attach one? Is interrupt topology preventing
bring-up? Does the debugger see state for the second CPU? Do host threads show
that a second vCPU exists but never runs guest work?

The observability stack turns those into comparable facts:

- QEMU configuration and live vCPU inventory;
- OpenBoot and machine-description CPU topology;
- Solaris enumeration, attach, and scheduler evidence;
- SPARC registers and execution state through GDB; and
- exact-QEMU-PID host thread and trace evidence.

The goal is not merely to collect an impressive pile of diagnostics. It is to
find the cheapest observation that makes one ownership hypothesis survive and
another die, make a focused change, and repeat.

These examples changed the framing of the project. The MCP is not primarily a
way to operate an antique VM. It is a repair loop for bugs that cross userland,
kernel, driver, firmware, emulator, and host boundaries. A working self-hosted
Solaris VM gave us somewhere real to stand. The control plane gives us a way to
move, see what changed, and avoid getting lost.
