# An old Sun box gets a control plane

*August 27, 2026*

I have a working, self-hosted Solaris SPARC VM. Solaris runs on an emulated
Niagara machine in QEMU, which runs inside a VM on another Mac. The lab already
has serial and maintenance channels, persistent disks, run manifests, semantic
state classification, live GDB-stub debugging, and host-side performance
measurements.

The machine boots. I want a Codex agent to work from this premise:

> Huh. I'm running on a Solaris SPARC host from 2002. Weird. Welp, I have Bash.
> Let's fucking go.

The guest is the agent's immediate subject, but the agent can inspect QEMU,
emulated CPU state, SPARC registers, host tracing, disks, firmware, logs, and
the console. Guest networking is under development, so the control plane cannot
depend on SSH into the guest.

The first README defines the intended operating style: exact targets, bounded
commands, explicit mutation, and verified cleanup. The agent can use expert
tools without guessing which QEMU process it has attached to or leaving the VM
paused after a debugger session.

The project also uses my Gilfoyle hypothesis method. An investigation states
competing falsifiable explanations, predicts the evidence for each one, runs a
cheap discriminating test, and records the result with its source layer. Console
output, QEMU state, and host activity remain separate kinds of evidence.

This repository is heavily vibe-coded. I am using a SPEC, implementation plans,
tests, and a canonical TODO file to keep that development style from turning
the project into a pile of undocumented experiments.

The first implementation work covers strict configuration, run-root
containment, exact PID identity, stable evidence envelopes, and tests that need
neither a live guest nor root access.
