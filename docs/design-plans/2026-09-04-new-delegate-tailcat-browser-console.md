# new-delegate and the Tailcat browser console

## Product intent

`https://console.unix.wtf/` will be a static single-page application that can
attach to a console published from another machine. The console may belong to
QEMU, UTM, VirtualBox, or a USB serial adapter. A local helper opens the console
endpoint, starts an ephemeral Tailcat server, and displays a `tc...` pairing
address. The user gives that address to the web console and receives an xterm.js
terminal without exposing an inbound port on the machine running the helper.

The web application has no console relay or session backend. Its HTTP host
serves static files. Console traffic travels between the browser's Tailcat
client and the helper. The static origin must not receive the pairing address
or console bytes.

```text
QEMU / UTM / VirtualBox / USB serial
                 |
        Unix, TCP, or serial endpoint
                 |
      new-delegate publishing helper
                 |
       Tailcat and WireGuard via DERP
                 |
       Go Tailcat client in WebAssembly
                 |
               xterm.js
```

## Browser boundary

Tailcat's browser demo works by compiling the Go Tailcat client to WebAssembly.
It is not an ordinary JavaScript Tailcat implementation. The SPA must ship a
pinned Go/WASM module and the matching Go runtime support. JavaScript connects
xterm.js to a narrow WASM interface for dialing, reading bytes, writing bytes,
reporting connection state, and closing the client.

The browser transport currently uses DERP over WebSockets. It does not perform
Tailcat's native direct UDP upgrade. This is acceptable for an interactive
serial console, but the UI must identify DERP connection failures accurately
and must not promise a direct path.

Tailcat does not promise API, CLI, or wire stability. Pin its module version,
hide it behind a small adapter, record the WASM artifact's source revision and
checksum, and test the native helper against the exact browser artifact shipped
by the site.

Relevant upstream material:

- <https://github.com/tailscale/tailcat>
- <https://tailscale.com/blog/tailcat>
- <https://github.com/tailscale/tailcatchat>
- <https://github.com/tailscale/tailcat/issues/4>

## new-delegate reuse

The sibling `new-delegate` project is the preferred transport engine. It
already has a typed two-address grammar, a shared byte-stream bridge, and an
in-process Tailcat adapter. The committed checkpoint at `5c35ecc` executes
ordinary `TCP-LISTEN -> TCP-CONNECT` routes. Earlier checkpoints pin Tailcat
v0.6.0, validate pairing addresses through Tailcat's parser, create fresh keys
in memory, filter one Tailcat virtual port, reuse one pairing for sequential
streams, and prove a live repeated-stream pairing through Tailcat's public
infrastructure.

The current grammar includes:

```text
TAILCAT-LISTEN:8080
TAILCAT-CONNECT:@stdin
TCP-LISTEN:127.0.0.1:18080
TCP-CONNECT:127.0.0.1:8080
```

The geographic CLI arrangement remains useful:

```text
right side:
  delegate TAILCAT-LISTEN:8080 TCP-CONNECT:127.0.0.1:8080

left side:
  delegate TCP-LISTEN:127.0.0.1:18080 TAILCAT-CONNECT:@stdin
```

For the SPA, the browser's WASM client replaces the left-side native process.
The publishing helper remains the right side. The desired QEMU form is:

```text
delegate TAILCAT-LISTEN:7000 UNIX-CONNECT:/path/to/console.sock
```

`new-delegate` does not yet have `UNIX-CONNECT`, `UNIX-LISTEN`, or a serial
endpoint. Add `UNIX-CONNECT` before integrating a real QEMU console. Direct
serial support can follow as a typed endpoint with explicit device, baud, data
bits, parity, stop bits, and flow-control settings. QEMU, UTM, and VirtualBox
launch adapters should resolve their hypervisor-specific state to one of these
typed stream endpoints rather than adding hypervisor logic to the bridge.

The `new-delegate` working tree on 2026-09-04 contains uncommitted route wiring
for both Tailcat halves in:

- `cmd/delegate/address_route.go`
- `cmd/delegate/address_route_test.go`
- `cmd/delegate/main.go`

Focused command-package tests and the race test passed during development. The
full project gate, commit, push, two-host proof, and corresponding Woodpecker
run were still pending when work paused. `PROJECT_STATUS.md` and the untracked
design and implementation-plan directories also remain uncommitted there.

Native build work is limited to Darwin/arm64 and Linux/amd64 until the owner
changes that scope. The browser's `js/wasm` artifact is part of the web product,
not an additional native platform target.

## Helper lifecycle

Each helper start creates a fresh in-memory Tailcat key and pairing address.
The address remains reusable while the helper runs so a browser can disconnect
and reconnect. Stopping the helper revokes the address and closes the console
endpoint. A second simultaneous consumer is rejected in the initial design.

The helper must bind its lifetime to the exact console producer. A Unix socket
pathname is insufficient identity because a restarted VM may create a new
socket at the same path. The launcher or adapter must retain and revalidate the
VM process identity, start time, configured endpoint, and socket identity.
When those change, it must stop the Tailcat server and issue a new pairing
address for the new console instance.

QEMU and VM-manager launchers should start the helper with the machine and show
the pairing address in their normal launch output. A USB serial launcher should
open and own the device before announcing the address. A QR code and copyable
site link may be derived from the address, subject to the capability-handling
decision below.

## Capability handling

The Tailcat pairing address is a bearer capability. Anyone who obtains it can
race to claim the active console. It must not appear in process arguments,
environment variables, logs, tracebacks, telemetry, analytics, crash reports,
cookies, or persistent browser storage. The helper should print it only on the
explicit operator output channel. Native clients should receive it through a
private inherited descriptor or standard input.

The existing design requires the user to paste the address and keeps it only in
page memory. This conversation also considered a fragment link such as
`https://console.unix.wtf/#tc=...`, following Tailcatchat's static-site pattern.
A URL fragment is not sent in the HTTP request, but it can remain in browser
history and may be visible to extensions, screenshots, or client-side code.
Keep paste-only memory handling as the requirement until the owner explicitly
accepts fragment-link exposure.

The existing local Python console separates human access from MCP writes and
can persistently block the MCP writer. The first Tailcat publisher currently
assumes one full read/write consumer. A browser policy that attaches read-only
and requires an explicit `Take control` action was proposed but not selected.
Do not add a handshake or a second capability until that choice is made.

## Relationship to the Python console

The consolidated Python console contains useful behavior that should remain:

- bounded console history;
- one broker owning the endpoint;
- explicit target discovery and selection;
- authenticated local control for MCP reads and writes;
- persistent human control over whether MCP writes are allowed; and
- browser connection status that does not claim the guest is healthy.

The public SPA should not require that Python service. Tailcat WASM and
new-delegate carry the remote data path directly. Python may remain the local
broker and MCP control plane when fanout, bounded history, or agent write policy
is needed. A transparent helper can be used when one browser owns the raw
console stream.

The current broker reconnect loop can retain a connector after the discovered
process has died. It may reconnect to a reused socket path without proving that
the new listener belongs to the selected process. Correct this before combining
automatic rediscovery with a long-lived Tailcat address.

## Static deployment on Maplewood

`console.unix.wtf` already has an A record for `192.99.36.83` with a 3600-second
TTL. Maplewood currently runs Docker containers behind `nginxproxy/nginx-proxy`
on public ports 80 and 443, with `nginxproxy/acme-companion` for certificates.
Existing static nginx containers such as `maggie-codes` use that ingress.

No container or nginx virtual host currently serves `console.unix.wtf`. The
deployment should add a static nginx container with the expected virtual-host
and certificate metadata. It should expose only the built HTML, CSS, JavaScript,
xterm.js assets, Go runtime support, and Tailcat WASM file. It needs no public
Tailcat, WebSocket relay, console API, database, OAuth service, or session
backend.

Use a strict content security policy, `Referrer-Policy: no-referrer`, no
third-party scripts, no analytics, and no service behavior that persists a
pairing address. Access-log verification should show only static asset requests.

## Test and delivery sequence

- Finish and commit `new-delegate`'s current Tailcat route wiring. Run the full
  race-enabled gate, push the checkpoint, and verify Biggie Woodpecker at the
  exact commit.
- Add `UNIX-CONNECT` with byte-exact, cancellation, half-close, path validation,
  and cleanup tests. Prove `TAILCAT-LISTEN -> UNIX-CONNECT` against a disposable
  Unix console fixture.
- Build the smallest Go/WASM adapter around the pinned Tailcat client. Keep
  pairing parsing, dialing, stream ownership, and closure inside Go. Expose a
  bounded byte and status interface to JavaScript.
- Connect the WASM adapter to xterm.js and test keyboard input, binary output,
  disconnect, reconnect, terminal resize, bounded scrollback, and capability
  erasure on reload.
- Run an interoperability test using the exact native helper and WASM artifact.
  Confirm that no pairing address or console byte reaches the static HTTP
  server.
- Add launch adapters for one QEMU console first, then UTM, VirtualBox, and USB
  serial without changing the Tailcat or browser contracts.
- Build the SPA container and attach it to Maplewood's existing nginx-proxy and
  certificate flow. Verify `https://console.unix.wtf/` before documenting it as
  available.

The local Darwin/arm64 gate and Biggie Linux/amd64 Woodpecker gate remain the
native release authority. GitHub may mirror the public source and documentation,
but a green mirror does not replace the exact Woodpecker checkpoint.
