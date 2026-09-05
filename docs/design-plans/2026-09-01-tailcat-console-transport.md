# Tailcat console transport for browsers and MCP

> Access update (2026-09-04): the owner selected GitHub OAuth restricted to
> `ryancnelson` / numeric ID `347171`, superseding this document's no-login rule.
> See `2026-09-04-pipeline-console-discovery.md` and SPEC 15.3 for the static
> WASM data path plus authentication/invitation service boundary.

## Goal

Let a browser or MCP agent attach to an arbitrary serial-console Unix socket
without opening an inbound port, joining a tailnet, or routing the console
through infrastructure operated by this project.

## Boundary

The first version accepts an explicit Unix stream socket. It does not discover
QEMU processes, UTM or VMware machines, containers, or physical serial ports.
Later adapters may discover those sources, but each adapter must resolve to the
same explicit socket contract before the relay starts.

The console source is opaque. The relay preserves bytes and does not interpret
terminal escape sequences, prompts, guest state, or emulator health.

## Selected design

The system has a publishing helper and two consumer paths:

```text
serial-console producer
        |
Unix stream socket
        |
console-share publisher
        |
Tailcat server and WireGuard tunnel
        |
DERP relay
        +-> Tailcat WebAssembly in the browser -> xterm.js
        |
        +-> bundled Tailcat client -> MCP console session -> agent tools
```

The hosted site serves HTML, CSS, JavaScript, xterm.js, the Go WebAssembly
runtime, and a pinned Tailcat WebAssembly module. It has no console API,
account database, session service, or server-side Tailcat process. The browser
calls Tailcat's `tailcatDial` WebAssembly interface, then connects the returned
pull-based byte stream to xterm.js. Browser Tailcat currently uses DERP over
WebSockets; direct UDP upgrade is unavailable in the browser.

The planned public origin is `https://console.unix.wtf/`. Its production host
serves only the static build; host-specific deployment details remain in an
operator-private runbook and are not part of this portable design. This static
application is distinct from the authenticated server-side shared-console
design in Section 15.2 of the specification.

The local `console-share` publisher embeds the Tailcat Go library. Each start
creates a fresh in-memory server key, prints the resulting `tc...` address, and
waits for a consumer. The key is never written to disk. The address stops
working when the publisher exits.

The MCP distribution includes a private Go Tailcat client. The Python MCP
starts that client as a managed child process and exchanges raw console bytes
over pipes. Users do not install or invoke Tailcat separately. The Tailcat
address reaches the child through a private inherited pipe rather than a
process argument, environment variable, file, or log record.

## Command interface

The publisher requires one socket mode:

```text
console-share --connect /path/to/console.sock
console-share --listen /path/to/console.sock
```

`--connect` dials a Unix stream socket created by the console producer.
`--listen` creates the Unix stream socket and waits for one producer to dial it.
Supplying both modes or neither is an error.

Listen mode may remove a stale socket only after proving that the path is a
socket and that no process accepts a connection there. It must refuse regular
files, directories, symlinks, and unknown path types. Shutdown removes only the
socket created by that publisher instance.

The first version has no launch command, process discovery, saved profiles, or
automatic socket selection. Those features belong in source-specific adapters
after the explicit interface is proven.

## Session and ownership

The Tailcat address is an unlisted session capability. The hosted page has no
additional login. The user copies the fresh address from the publisher and pastes
it into the browser.

The page holds the address in memory only. It does not put the address in a URL,
query string, fragment, cookie, local storage, session storage, telemetry, or
error report. Reloading or leaving the page clears it.

One consumer owns the serial stream at a time. The publisher rejects another
Tailcat connection while a browser or MCP session is active. After that
consumer disconnects, the same address may attach one replacement consumer
while the publisher remains running. The publisher does not broadcast output
or merge input from multiple clients.

This policy prevents competing cursors and interleaved keystrokes. It does not
make the address safe to publish. Anyone who obtains the address can race to
become the active client.

## MCP behavior

Provisioning is outside this feature. A cloud, Proxmox, local VM, container, or
hardware workflow may return a logical run identity plus a fresh Tailcat
console address. The MCP accepts that address at runtime and creates an
in-memory remote-console session. It does not need to know how the source was
started.

Attaching requires a reason and returns an opaque local session ID. The address
is a capability and must not appear in MCP envelopes, evidence records, logs,
tracebacks, process listings, or persistent configuration. Run identity is
recorded separately and retains the provenance supplied by the provisioner.

The MCP exposes attach, status, bounded read, write, and detach operations.
Writes retain the existing reason and mutation requirements. The MCP keeps
bounded console history in memory and disables writes after transport failure
or detach. Detach closes the child client and proves that it exited. MCP
shutdown detaches every active remote console with the same bounded cleanup.

The private Go client dials a supplied Tailcat address and exposes the stream
to its parent. A dedicated inherited file descriptor carries the address
during startup, then closes. Standard input and output are reserved for console
bytes; standard error contains bounded diagnostics with capabilities redacted.
The Python process treats malformed startup messages, early child exit, and
cleanup timeout as typed transport failures.

## Byte and lifecycle behavior

The publisher copies bytes unchanged between the Tailcat stream and Unix socket.
It uses independent copy loops so input and output may progress concurrently.
EOF in one direction triggers the corresponding half-close when supported.
Failure or completion closes both streams and waits for the copy loops before
accepting a replacement consumer.

In connect mode, a missing or refused socket leaves the Tailcat listener alive
and reports that the console source is unavailable. A later consumer may retry;
the publisher attempts a fresh Unix connection for each accepted consumer.

In listen mode, the publisher waits for the console producer before declaring the
console connected. The relationship between producer and consumer must be
defined during implementation: the recommended rule is to keep one accepted
producer connection and allow browser replacement against it until either side
closes. A producer disconnect returns the publisher to the producer-waiting state.

SIGINT and SIGTERM close the active consumer, Tailcat server, Unix connection,
and owned listener. Shutdown is bounded. Failure to remove an owned socket is
reported without deleting any broader path.

## Browser behavior

The initial page shows an address field and Connect button before loading the
terminal. Connection states are `loading`, `ready`, `connecting`, `connected`,
`disconnected`, and `failed`. Errors distinguish invalid address, DERP-map
failure, timeout, occupied publisher, and console-source failure when the publisher
can communicate it.

For the browser consumer, console output is written to xterm.js as bytes decoded by its terminal path.
Terminal input is encoded and sent through Tailcat. The UI provides Disconnect
and Clear controls. It does not provide lifecycle buttons because an arbitrary
serial socket has no common reset, power, or break-control protocol. Sending a
serial break may be added only after defining a transport-independent control
contract.

Scrollback is bounded. Input is disabled whenever the Tailcat stream is not
connected. Reconnection is explicit so a page does not repeatedly consume the
single-client slot after a failure.

## Dependencies and distribution

The publisher and private MCP client share a Go module in this repository.
It pins a reviewed Tailcat version because Tailcat makes no API, CLI, or wire
stability promise. The browser module is built from the same pinned dependency
and checked into or attached to releases as a reproducible artifact. Generated
files record their source version and checksum.

The distribution must include Tailcat's BSD-3-Clause notice, xterm.js notices,
and notices required by the linked WebAssembly dependencies. Releases should
begin with supported Unix hosts that pass the test suite. Illumos support
requires a separate compile and live-network probe; no documentation may imply
support based only on Go's `GOOS=illumos` target.

## Validation

Unit tests use temporary Unix sockets and an injectable in-memory stream to
prove exact bidirectional bytes, half-close behavior, single-client exclusion,
replacement after disconnect, safe path handling, signal cleanup, and fresh
keys across starts.

MCP tests use a fake child transport to prove runtime attach, address
redaction, bounded history, write policy, typed failure, detach, and child
cleanup. A native integration test joins the publisher through the bundled
client and proves that a browser cannot attach while the MCP owns the stream.

A hermetic Tailcat test uses a local DERP fixture where practical. A headless
browser test loads the static site, enters an address, sends terminal input,
receives console output, and proves that the static HTTP origin receives no
address or console request. It also checks that reload clears the address.

An opt-in live test connects to one disposable QEMU or equivalent console
socket. It records the socket identity, confirms that only one consumer may
attach, exercises browser and MCP input and output separately, exits the
publisher, and proves that the old address no longer connects and no owned Unix
socket remains.

## Deferred work

- Discovery menus for QEMU, UTM, VMware, containers, and physical serial ports.
- Saved source profiles and helper installation services.
- Native Windows named-pipe support.
- Configurable or self-hosted DERP maps.
- Stable addresses, multi-user sharing, recording, and replay.
- Emulator lifecycle controls and serial-break signaling.

## QEMU-native option

QEMU could eventually present a user experience such as a Tailcat chardev or
serial backend that prints a fresh address during VM startup and closes it with
the VM. That would remove the separate publisher command for QEMU while keeping
the consumer contract unchanged.

Tailcat is a Go library and QEMU is primarily C. Embedding a Go shared library,
reimplementing Tailcat's data plane in C, or teaching QEMU to manage a sidecar
have different build, lifecycle, portability, and upstream-maintenance costs.
The first implementation should preserve the explicit Unix socket as the
reference boundary. SUN-015 will compare those QEMU options after the generic
publisher proves the transport and cleanup contract.

The agent-facing stateful terminal and command-profile layer is also separate.
SUN-014 builds on this transport after its raw terminal semantics are designed.
