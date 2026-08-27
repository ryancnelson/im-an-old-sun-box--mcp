# An Old Sun Box Gets a Control Plane

*August 27, 2026*

This project began with a working, self-hosted Solaris SPARC VM and a useful
change in perspective.

The VM is already an improbable stack: Solaris on an emulated Niagara machine
inside QEMU, hosted by a VM on another Mac. It has serial and maintenance
channels, persistent disks, run manifests, semantic state classification, a
live GDB-stub workflow, and host-side performance evidence. It is not a toy
mockup waiting for someone to invent the machine. The machine boots. The
interesting work is what happens next.

The perspective was to give a Codex agent an operating worldview that begins:

> Huh. I'm running on a Solaris SPARC host from 2002. Weird. Welp, I have Bash.
> Let's fucking go.

That guest-first worldview is useful, but guest-only access would throw away
the best part of virtualization. The agent should be able to inhabit Solaris
while also looking through the walls: QEMU monitor state, emulated CPU state,
SPARC-aware GDB, host eBPF and perf, disks, firmware, logs, and the console.
Guest networking is itself under investigation, so none of this control plane
can depend on SSH into the guest.

The first README tried to get that spirit right. This is not a polite remote
shell with a Sun logo taped to it. It is a cross-layer laboratory with raw
expert power, exact targeting, bounded execution, visible mutation, and cleanup
that must be proved instead of implied.

It also adopted Ryan's Gilfoyle hypothesis method: state competing falsifiable
hypotheses, predict what each would cause, choose a cheap discriminating test,
record evidence immediately, and kill bad hypotheses without sentimentality.
A console twitch is not a diagnosis. A busy QEMU thread is not proof that
Solaris is progressing. Every fact says which layer produced it.

How vibe-coded is the project? Quite. There is no pretense that Ryan is a
solitary sun4v wizard. The work combines curiosity, AI collaboration, old
documentation, experiments, and evidence. That is why the repository began by
writing a normative SPEC, a test-first implementation plan, a canonical TODO
ledger, and a joining-and-contributing workflow. Vibe-coding is allowed;
vibe-project-management is not.

At the end of this first moment, the public repository had its voice and its
contract. The MCP implementation was beginning with the deliberately boring
parts that make the wild parts trustworthy: strict configuration, run-root
containment, exact PID identity, stable evidence envelopes, and fake-backed
tests that require neither a live guest nor root.

The box is old. The debugging rig is not.

