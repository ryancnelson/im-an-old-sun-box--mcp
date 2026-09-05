# The console does not need to be nearby

*September 1, 2026*

The web console currently running on my laptop knows too much about where the
machine lives. It connects to a local broker, which owns a local Unix socket,
which belongs to a particular QEMU run. That is fine for the old Sun lab. It is
also an accidental limit.

The useful object is smaller than the lab: a bidirectional stream of serial
console bytes presented as a Unix socket.

QEMU can produce one. A VM manager can be adapted to produce one. A container
can expose one. `socat` can bridge a physical serial port into one. Once that
socket exists, the rest of the console stack should not care which machine,
hypervisor, cloud, or pile of USB adapters produced it.

Tailcat arrived at exactly the right moment. It packages Tailscale's userspace
WireGuard, DERP, and NAT traversal pieces without requiring a Tailscale account
or changing host routes. A server prints a fresh `tc...` address. A client with
that address can establish an encrypted byte stream. Tailcat already proves
that its client can run as WebAssembly in a browser.

That suggests a simple public service. The site serves xterm.js and Tailcat
WebAssembly. It asks for a Tailcat address and connects from the browser. My
server never handles the console stream. It can serve a thousand pages without
becoming the serial-console concentrator for a thousand strangers.

The machine owner runs something like:

```text
console-share --connect /path/to/console.sock
```

or, when the console producer expects to dial a socket created by somebody
else:

```text
console-share --listen /path/to/console.sock
```

The publisher creates a new in-memory Tailcat key every time it starts. It
prints the address and accepts one consumer. When it exits, that address is
dead. There is no account system and no stable address to revoke later. The
address is the session capability, so losing it to a log or browser history is
still a security failure. The page keeps it in memory and nowhere else.

One consumer means one consumer. Serial terminals do not improve when two
independent keyboards race to edit the same command line. A disconnected
consumer releases the slot, but a second browser cannot join an active first
browser.

## The agent wants the same wire

The browser case exposed the larger idea. The MCP should be able to consume the
same address.

I want to tell an agent:

> Run VM xyz on my Proxmox server in London.

The agent may already know how to talk to that provisioner. I do not want this
project to absorb every cloud and hypervisor API. The provisioner can return a
run identity and a fresh Tailcat console address. The MCP attaches the address
as a built-in console transport and continues with bounded reads and deliberate
writes even if the new VM has no network service beyond its serial console.

Tailcat is written in Go and this MCP is Python. The planned distribution ships
a small Go client that the MCP manages privately. Users do not install Tailcat
or build a shell pipeline. The Python process passes the address through a
private inherited descriptor, waits for a bounded readiness result, and uses
the child's standard input and output for console bytes. Detach must prove that
the exact child exited.

The address must not appear in process arguments, environment variables,
evidence records, MCP envelopes, or logs. Run identity remains a separate fact.
Knowing that a console address came from a Proxmox operation does not prove
which guest is behind it unless the provisioner supplies and the MCP preserves
that provenance.

The browser and MCP share the publisher's one-consumer rule. An agent cannot
preempt a human terminal, and a browser cannot slip into an agent's active
session. The current owner must disconnect first.

## The deliberately boring first version

The first publisher takes an explicit socket path. It will not scan process
tables, guess which QEMU matters, inspect UTM configuration, enumerate VMware
machines, or hunt through physical serial devices. Those can become a menu of
source adapters after the byte path is proven.

The first tests use fake Unix sockets and a local DERP fixture. They must prove
byte-exact traffic, one-consumer ownership, replacement after disconnect, fresh
addresses, safe socket cleanup, MCP capability redaction, and browser privacy.
A later live test can use a disposable QEMU console without making guest
networking a prerequisite.

This is now SUN-004. The design and implementation plan are written. None of it
is shipped yet.

Two follow-ups are now explicit. SUN-014 defines the stateful terminal tools
that let an agent observe, type, wait, interrupt, and eventually use
environment-specific command profiles. SUN-015 asks whether QEMU should publish
the Tailcat address itself. A QEMU-native chardev would give the cleanest launch
experience, but Tailcat is Go and QEMU is C, so the design must compare a
managed sidecar with less attractive linking or reimplementation options.
