# I'm an Old Sun Box — MCP

> Solaris on SPARC, inside QEMU, inside another Mac, wired into an AI that ran
> `uname`, stared briefly into the abyss of 2002, and said:
>
> **“Huh. Weird. Welp, I have Bash. Let's fucking go.”**

This is a bespoke MCP control plane for a virtual Sun Niagara laboratory.

Start with the [normative specification](SPEC.md). Work is organized in the
[canonical TODO list](TODO.md), and the
[joining and contributing guide](JOINING-AND-CONTRIBUTING.md) explains how an
idea becomes a scoped branch, tested change, and cleanly closed piece of work.
The [project blog](project-blog/) keeps the chronological, irreverent story
without turning the normative docs into Friday-night word salad.
[Codex setup](docs/CODEX-CONFIG.md) covers direct installation on the VM host
and the SSH stdio path from another machine.

The point is not to give an agent a polite little remote shell and pretend an
ancient Solaris guest is a normal cloud VM. The point is to let the agent
**inhabit the machine** while also giving it the kind of impossible x-ray vision
that hardware and kernel hackers dream about:

- a shell inside the Solaris/illumos SPARC guest;
- guest-native DTrace: probes, aggregations, syscall/provider evidence, and the
  operating system explaining itself in its own native tongue;
- out-of-band serial and maintenance channels;
- QEMU monitor and machine-state access;
- a SPARC-aware GDB looking directly at the emulated CPU;
- host-side eBPF, perf, syscall, scheduler, and I/O evidence;
- VM disks, snapshots, logs, firmware, and run manifests; and
- an evidence ledger for keeping facts separate from vibes.

Guest networking is one of the things being debugged. It is therefore **never
the prerequisite for debugging it**.

## What this is for

The payoff is a tight repair loop for failures that cross historical and
virtualization boundaries. Suppose Solaris `ifconfig` barfs on an unexpected
ioctl. The bug might live in userland assumptions, the illumos networking
stack, Ryan's emulated Solaris device driver, QEMU's sun4v/device model, or the
lab configuration connecting them.

This MCP is the apparatus for refusing to guess. Reproduce the symptom, state
competing layer-specific hypotheses, observe the ioctl with guest DTrace,
inspect kernel/driver state, correlate it with QEMU and host traces, patch the
most likely owner, rebuild, reboot or reload deliberately, and run the same
discriminating test again. That iterative cross-layer loop is the product.

The same applies when `-smp 2` still produces a one-CPU Solaris system. We can
compare QEMU's vCPU inventory, OpenBoot and sun4v machine description data,
Solaris CPU discovery/attach evidence, debugger-visible CPU state, and host
threads instead of treating “other people got SMP working” as an actionable
diagnosis.

## The worldview

The guest is the primary subject:

```text
Solaris processes and kernel
        ↕
SPARC CPU, memory, traps, and devices
        ↕
QEMU monitor, console, and GDB stub
        ↕
VM host tracing, networking, and storage
```

The agent begins at the layer nearest the symptom and crosses layers whenever a
discriminating test calls for it. A fact always says where it came from. A guest
observation is not a QEMU observation; a QEMU observation is not a host
observation; and a hot host thread is not proof that Solaris is making progress.

This is less “SSH into a server” and more “mind-meld with virtualized bare SPARC
metal.”

## The method

The project follows Ryan's Gilfoyle hypothesis method:

1. State competing, falsifiable hypotheses.
2. Predict what each hypothesis says we should observe.
3. Run the cheapest test that distinguishes them.
4. Record the evidence immediately, including its layer and provenance.
5. Kill bad hypotheses without sentimentality.
6. Change the system only after the pre-change evidence is safely in the bag.

No séance-by-logfile. No declaring victory because the console twitched. No
turning “I don't know” into a page of confident fan fiction.

## The Thoth inheritance

Ryan spent five years at Joyent, and this project knowingly borrows an
operational idea from [manta-thoth](https://github.com/TritonDataCenter/manta-thoth).
Thoth took illumos core and crash dumps, gave each dump a stable identity,
stored its metadata, and ran named analyzers against it. An engineer could
debug one dump interactively, turn the useful part of that session into an
analyzer, and apply the analyzer to later dumps.

Thoth predates OpenAI. Its useful idea is operational: debugging should not
hold recovery hostage. The corresponding workflow for this lab is:

```text
wedged VM
    -> freeze the exact run
    -> capture and hash its diagnostic state
    -> verify the capture is durable
    -> hand the case to offline debugging and named analyzers

known inputs
    -> start a replacement VM
    -> prove its identity and boot progress
```

The sealed case should contain enough material to investigate after the
original QEMU process is gone: run inputs and hashes, console history, QMP
state, guest memory or a crash dump where supported, debugger captures, tool
versions, and evidence provenance. Analyzer results belong to the case without
rewriting its original evidence.

The dump and replacement are separate transactions. The wedged run survives
until its capture is readable and verified. A successful dump does not prove
the replacement booted, and a booting replacement does not excuse a corrupt or
incomplete dump.

This lifecycle is planned, not shipped. SUN-009 defines content-addressed
captures and analyzers. SUN-010 defines the freeze, seal, handoff, replacement,
and rollback state machine.

## House rules

- **Out-of-band first.** Serial sockets, QEMU monitor, and debugger access must
  survive a broken guest network.
- **Exact targets only.** No `pgrep qemu | head -1` cowboy shit when several
  irreplaceable experiments may be running.
- **Every mutation confesses.** Monitor controls, signals, debugger writes,
  register reads with acknowledge side effects, and disk operations are labeled
  as state-changing.
- **Detach the debugger.** A clever diagnostic that silently leaves every vCPU
  stopped is not clever.
- **One writer means one writer.** Shared channels do not become more reliable
  when three stale bridge processes fight over them.
- **Never Ctrl-C QEMU's controlling terminal.** We have already paid tuition for
  that lesson.
- **Snapshots before crimes.** Reproducible crimes are science.
- **Evidence beats confidence.** Especially when confidence is wearing a Sun
  Microsystems T-shirt.

## What this MCP should expose

The intended tool families are explicit about the layer they operate on:

```text
lab.*          run discovery, intent, health, and manifests
guest.*        bounded guest commands, console evidence, and DTrace
qemu.*         HMP/QMP queries and deliberate machine control
debugger.*     SPARC register, instruction, memory, and backtrace capture
host.trace.*   bounded eBPF/perf/process investigations
evidence.*     append-only observations and artifact references
hypothesis.*   predictions, discriminating tests, and falsification
capture.*      planned immutable diagnostic cases and content identity
analyzer.*     planned offline metadata extraction and diagnosis
lifecycle.*    planned wedge capture and replacement-VM rollover
```

Raw expert access is a feature, not an embarrassment. The answer to dangerous
power is precise targeting, bounded execution, visible effects, and recoverable
experiments—not sanding every tool down until it can only print `hello world`.

DTrace inside the guest and eBPF/perf outside QEMU are complementary x-ray
angles. Neither is promoted into evidence from the other layer: a DTrace probe
describes Solaris; a host probe describes the emulator process. When they agree
across the virtualization boundary, now we're cooking.

## Status

**The portable 0.1 core is implemented, and the first live profile is proven.**
Strict configuration, validated run identity, guest/HMP/QMP/host adapters,
immutable evidence and hypothesis history, and the MCP stdio server are covered
by 58 tests. CI runs the portable suite on macOS and Linux.

The Niagara profile has also been exercised against a live QEMU 10.2 run. It
proved the exact PID, queried QMP over a private Unix socket, captured SPARC v9
registers and instructions with `gdb-multiarch`, detached, and independently
proved that QEMU returned to `running`. A fresh Codex CLI on the VM host then
discovered the run and queried its status using only MCP tools.

Guest DTrace recipes, named host eBPF/perf recipes, the project semantic
classifier, content-addressed diagnostic captures, and automatic wedge rollover
remain tracked work rather than advertised magic.

The box is old. The debugging rig is not.

## How vibe-coded is this?

Quite!

**I'm leaning into the AI-slop writing style, rather than trying to act like
I'm a poet. Expect em-dashed gems like “*The spirit is captured, but
nobody—including future Ryan—can quickly tell what the software promises or
what to do next.*” in big helpings.**

There are no illusions here that Ryan emerged fully formed from the forehead of
Bill Joy, already fluent in sun4v internals. This project is being built through
curiosity, experiments, AI collaboration, old documentation, new evidence, and
the occasional extremely productive bad idea.

That makes discipline more important, not less. The SPEC says what the system
must do. Tests prove what it actually does. The evidence ledger records what we
actually observed. The contributor workflow keeps a promising hack from
quietly becoming an archaeological layer.
