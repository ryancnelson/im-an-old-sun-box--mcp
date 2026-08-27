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

The point is not to give an agent a polite little remote shell and pretend an
ancient Solaris guest is a normal cloud VM. The point is to let the agent
**inhabit the machine** while also giving it the kind of impossible x-ray vision
that hardware and kernel hackers dream about:

- a shell inside the Solaris/illumos SPARC guest;
- out-of-band serial and maintenance channels;
- QEMU monitor and machine-state access;
- a SPARC-aware GDB looking directly at the emulated CPU;
- host-side eBPF, perf, syscall, scheduler, and I/O evidence;
- VM disks, snapshots, logs, firmware, and run manifests; and
- an evidence ledger for keeping facts separate from vibes.

Guest networking is one of the things being debugged. It is therefore **never
the prerequisite for debugging it**.

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
guest.*        bounded guest commands and console evidence
qemu.*         HMP/QMP queries and deliberate machine control
debugger.*     SPARC register, instruction, memory, and backtrace capture
host.trace.*   bounded eBPF/perf/process investigations
evidence.*     append-only observations and artifact references
hypothesis.*   predictions, discriminating tests, and falsification
```

Raw expert access is a feature, not an embarrassment. The answer to dangerous
power is precise targeting, bounded execution, visible effects, and recoverable
experiments—not sanding every tool down until it can only print `hello world`.

## Status

**Specification complete; initial implementation in progress.** The
control-plane design is being extracted from a working
QEMU sun4v laboratory that already has guest channels, persistent storage,
semantic VM classification, live GDB-stub debugging, and host-side performance
evidence.

The box is old. The debugging rig is not.

## How vibe-coded is this?

Quite!

There are no illusions here that Ryan emerged fully formed from the forehead of
Bill Joy, already fluent in sun4v internals. This project is being built through
curiosity, experiments, AI collaboration, old documentation, new evidence, and
the occasional extremely productive bad idea.

That makes discipline more important, not less. The SPEC says what the system
must do. Tests prove what it actually does. The evidence ledger records what we
actually observed. The contributor workflow keeps a promising hack from
quietly becoming an archaeological layer.
