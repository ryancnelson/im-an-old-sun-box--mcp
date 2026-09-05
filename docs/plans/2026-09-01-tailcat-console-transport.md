# Tailcat console transport implementation plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Build a local publisher, static browser terminal, and native MCP transport that connect one explicit serial-console Unix socket to either a human or agent through Tailcat.

**Architecture:** A Go publisher embeds a pinned Tailcat server, creates a fresh address for every process, and bridges one active Tailcat TCP stream to a Unix stream socket in connect or listen mode. A static xterm.js page dials through Tailcat WebAssembly, while the Python MCP manages a bundled Go Tailcat client and exposes runtime attach, status, read, write, and detach tools.

**Tech stack:** Go, `github.com/tailscale/tailcat`, Unix sockets, Go WebAssembly, plain JavaScript, xterm.js, pytest, and a headless Chromium integration test.

---

### Task 1: Establish the Go module and pin Tailcat

**Files:**

- Create: `relay/go.mod`
- Create: `relay/go.sum`
- Create: `relay/internal/tailcatserver/server.go`
- Create: `relay/internal/tailcatserver/server_test.go`
- Modify: `.gitignore`

**Step 1: Create the feature branch and worktree**

Create `codex/sun-004-tailcat-console-transport` from current `main` using the
repository worktree workflow. Change SUN-004 from `ready` to `active` and add
the branch and owner before implementation.

**Step 2: Write the failing lifecycle test**

Define a narrow internal interface so the rest of the helper does not depend
directly on Tailcat's unstable API:

```go
type Listener interface {
    Address() string
    Close() error
}

func Start(ctx context.Context, accept func(net.Conn)) (Listener, error)
```

The test starts two listeners and asserts that both addresses begin with `tc`
and differ. It closes each listener and asserts that `Close` is idempotent.

**Step 3: Run the test and verify failure**

Run: `cd relay && go test ./internal/tailcatserver -run TestFreshAddressAndClose -v`

Expected: FAIL because `Start` is undefined.

**Step 4: Pin and wrap Tailcat**

Initialize the module, pin a reviewed Tailcat release rather than `latest`, and
implement `Start` with an in-memory key and `tailcat.Server.OnTCP`. Keep the
Tailcat address and concrete server private to this package. Do not expose key
persistence.

**Step 5: Run the package tests**

Run: `cd relay && go test ./internal/tailcatserver -v`

Expected: PASS.

**Step 6: Record dependency provenance**

Add the pinned tag and resolved module version to the design document if they
differ. Add generated helper binaries and WebAssembly outputs to `.gitignore`.

**Step 7: Commit**

```bash
git add .gitignore relay/go.mod relay/go.sum relay/internal/tailcatserver docs/design-plans/2026-09-01-tailcat-console-transport.md
git commit -m "build(relay): pin Tailcat behind a narrow server interface"
```

### Task 2: Implement byte-exact stream bridging

**Files:**

- Create: `relay/internal/bridge/bridge.go`
- Create: `relay/internal/bridge/bridge_test.go`

**Step 1: Write bidirectional tests**

Use paired in-memory or loopback connections. Send binary fixtures containing
NUL, invalid UTF-8, terminal escapes, CR, and LF in both directions. Assert the
received bytes are identical.

Add tests for EOF, one-sided failure, context cancellation, and completion of
both copy loops. The public function is:

```go
func Copy(ctx context.Context, console, remote net.Conn) error
```

**Step 2: Run the tests and verify failure**

Run: `cd relay && go test ./internal/bridge -v`

Expected: FAIL because `Copy` is undefined.

**Step 3: Implement the bridge**

Run two `io.Copy` operations under one cancellation context. When one side
reaches EOF, call `CloseWrite` on the opposite connection when available.
Close both connections on cancellation or hard failure. Wait for both copy
goroutines before returning. Do not decode, normalize, log, or buffer the
console contents.

**Step 4: Run race-tested package tests**

Run: `cd relay && go test -race ./internal/bridge -v`

Expected: PASS with no race report.

**Step 5: Commit**

```bash
git add relay/internal/bridge
git commit -m "feat(relay): bridge console bytes without interpretation"
```

### Task 3: Add explicit Unix socket modes

**Files:**

- Create: `relay/internal/endpoint/endpoint.go`
- Create: `relay/internal/endpoint/endpoint_unix_test.go`

**Step 1: Write connect-mode tests**

Test successful dialing, missing path, connection refusal, and cancellation.
Expose:

```go
type Endpoint interface {
    Acquire(context.Context) (net.Conn, error)
    Close() error
}

func Connect(path string) Endpoint
func Listen(path string) (Endpoint, error)
```

**Step 2: Write listen-mode safety tests**

Prove that listen mode:

- creates a mode-restricted Unix stream socket;
- refuses a regular file, directory, or symlink;
- refuses a socket with a live listener;
- accepts one producer and can accept a replacement after disconnect;
- removes its own socket on close; and
- never removes a path replaced after startup.

**Step 3: Run the tests and verify failure**

Run: `cd relay && go test ./internal/endpoint -v`

Expected: FAIL because the endpoint package does not exist.

**Step 4: Implement connect and listen endpoints**

Use `net.Dialer.DialContext` for connect mode. For listen mode, capture the
created socket's device and inode and verify both before cleanup. Refuse to
unlink any non-socket. Keep producer acceptance independent of browser
acceptance.

**Step 5: Run race-tested endpoint tests**

Run: `cd relay && go test -race ./internal/endpoint -v`

Expected: PASS.

**Step 6: Commit**

```bash
git add relay/internal/endpoint
git commit -m "feat(relay): support explicit Unix connect and listen modes"
```

### Task 4: Enforce one active consumer session

**Files:**

- Create: `relay/internal/session/session.go`
- Create: `relay/internal/session/session_test.go`

**Step 1: Write ownership tests**

Define:

```go
type Gate struct { /* private state */ }
func (g *Gate) TryAcquire() (release func(), ok bool)
```

Test that the first acquisition succeeds, concurrent acquisitions fail, a
double release is harmless, and one new acquisition succeeds after release.
Run the contention case repeatedly under the race detector.

**Step 2: Run the tests and verify failure**

Run: `cd relay && go test -race ./internal/session -v`

Expected: FAIL because `Gate` is undefined.

**Step 3: Implement the gate**

Use a mutex-protected boolean or a capacity-one token channel. Return an
idempotent release closure. Do not queue extra browsers because a queued client
could acquire the console long after the user believes its attempt failed.

**Step 4: Run the tests**

Run: `cd relay && go test -race ./internal/session -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add relay/internal/session
git commit -m "feat(relay): limit console ownership to one consumer"
```

### Task 5: Build the `console-share` command

**Files:**

- Create: `relay/cmd/console-share/main.go`
- Create: `relay/cmd/console-share/main_test.go`
- Create: `relay/internal/share/share.go`
- Create: `relay/internal/share/share_test.go`

**Step 1: Write CLI validation tests**

Test `--connect`, `--listen`, both supplied, neither supplied, an empty path,
unknown flags, and `--help`. Invalid invocations must exit nonzero without
starting Tailcat or touching a socket.

**Step 2: Write orchestration tests**

Inject fake Tailcat listeners and endpoints. Prove that the command prints one
address to stdout, sends diagnostics to stderr, rejects a second browser,
bridges the active consumer, releases ownership after disconnect, and closes
every owned resource after cancellation.

**Step 3: Run the tests and verify failure**

Run: `cd relay && go test ./cmd/console-share ./internal/share -v`

Expected: FAIL because the command and orchestrator do not exist.

**Step 4: Implement orchestration**

Wire the endpoint, session gate, bridge, and Tailcat wrapper together. Install
SIGINT and SIGTERM cancellation. Print the address only after Tailcat starts.
Never print keys, console bytes, or pasted input. Return stable messages for an
occupied browser slot and unavailable console source where Tailcat permits it;
otherwise close rejected streams immediately.

**Step 5: Run the complete Go suite**

Run: `cd relay && go test -race ./...`

Expected: PASS.

**Step 6: Run a manual fake-socket probe**

Use a disposable temporary directory and a local socket fixture. Confirm input
and output, Ctrl-C cleanup, and address changes across starts. Do not use a live
VM for this step.

**Step 7: Commit**

```bash
git add relay/cmd relay/internal/share
git commit -m "feat(relay): publish one Unix console through Tailcat"
```

### Task 6: Add the native MCP Tailcat transport

**Files:**

- Create: `relay/cmd/console-join/main.go`
- Create: `relay/cmd/console-join/main_test.go`
- Create: `src/old_sun_mcp/tailcat_transport.py`
- Create: `src/old_sun_mcp/remote_console.py`
- Create: `tests/test_tailcat_transport.py`
- Create: `tests/test_remote_console.py`
- Modify: `src/old_sun_mcp/server.py`
- Modify: `src/old_sun_mcp/service.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_service.py`

**Step 1: Write native-client protocol tests**

The private `console-join` command receives the Tailcat address through an
inherited descriptor named by `--address-fd`. Standard input and output carry
console bytes. A second inherited descriptor named by `--status-fd` emits one
bounded JSON readiness or failure record, then closes.

Test missing descriptors, malformed addresses, connection timeout, exact
bidirectional bytes, parent cancellation, and capability redaction. Assert that
the address never appears in argv, environment, status JSON, or stderr.

**Step 2: Run the Go test and verify failure**

Run: `cd relay && go test ./cmd/console-join -v`

Expected: FAIL because the command does not exist.

**Step 3: Implement the private Go client**

Read and close the address descriptor before dialing. Use the same pinned
Tailcat module as the publisher. After connection, send `{"status":"ready"}`
through the status descriptor and copy stdin/stdout without text conversion.
On failure, return a stable code and redacted message. Bound dialing and
shutdown with contexts.

**Step 4: Write the Python child-transport tests**

Define a transport with this interface:

```python
class TailcatTransport:
    async def connect(self, address: str) -> ConsoleEndpoint: ...
    async def close(self) -> None: ...
```

Use a fake executable to prove descriptor passing, readiness parsing, timeout,
early exit, stderr bounds, console I/O, and termination escalation. Search all
captured values for the supplied address and fail on any disclosure.

**Step 5: Run the Python transport tests and verify failure**

Run: `uv run pytest tests/test_tailcat_transport.py -q`

Expected: FAIL because `TailcatTransport` does not exist.

**Step 6: Implement the Python transport**

Launch the bundled binary with `shell=False`, an explicit environment, and
private address and status pipes. Keep the address out of exceptions. Require a
valid ready record before returning the endpoint. On close, wait for bounded
exit, send terminate, then kill only the exact child if required.

**Step 7: Write remote-console session tests**

Test runtime attach with a logical run name and provenance, opaque session IDs,
bounded history, status, read, reason-required write, detach, transport loss,
MCP shutdown, and unknown session errors. Assert that envelopes and evidence
records never contain the Tailcat address.

**Step 8: Add MCP tools**

Register `guest.console_attach` and `guest.console_detach`. Extend
`guest.console_status`, `guest.console_read`, and `guest.console_write` to
accept an optional remote session ID while preserving configured local-broker
behavior. Attach and detach require a non-empty reason. Attach returns the
opaque session ID, logical run, provenance, and status, but never the address.

**Step 9: Run focused and complete tests**

Run:

```bash
uv run pytest tests/test_tailcat_transport.py tests/test_remote_console.py tests/test_server.py tests/test_service.py -q
cd relay && go test -race ./...
```

Expected: PASS.

**Step 10: Commit**

```bash
git add relay/cmd/console-join src/old_sun_mcp tests
git commit -m "feat(mcp): attach remote consoles through built-in Tailcat"
```

### Task 7: Build the pinned Tailcat browser module

**Files:**

- Create: `web/console-share/wasm/main_js.go`
- Create: `web/console-share/wasm/main_js_test.go`
- Create: `web/console-share/build_wasm.sh`
- Create: `web/console-share/vendor/TAILCAT-LICENSE`
- Create: `web/console-share/vendor/TAILCAT-VERSION`
- Create: `web/console-share/vendor/wasm_exec.js`
- Modify: `.gitignore`

**Step 1: Copy the smallest reviewed upstream wrapper**

Adapt Tailcat's `web/main_js.go` at the pinned version so it exposes only
`tailcatDial`. Preserve the pull-based connection methods:

```text
read() -> Promise<Uint8Array|null>
write(Uint8Array) -> Promise
closeWrite() -> Promise
close()
```

Remove listener, file-transfer, persistent-key, and local-storage surfaces.

**Step 2: Write WebAssembly API tests**

Use Go's existing js/wasm test strategy or a headless browser fixture to prove
that an empty address fails, a malformed address fails, the client key remains
ephemeral, and the connection exposes only the required methods.

**Step 3: Run the test and verify failure**

Run the exact js/wasm command documented by the pinned Tailcat source.

Expected: FAIL until the reduced wrapper exists.

**Step 4: Add a reproducible build script**

Build with `GOOS=js GOARCH=wasm`, the pinned module graph, and Tailcat's reviewed
release tags where applicable. Generate `main.wasm.gz` deterministically and
write its SHA-256 digest beside the artifact. Do not download code during the
static-site build.

**Step 5: Verify the artifact**

Run the build twice from clean output directories and compare digests.

Expected: identical `main.wasm.gz` hashes.

**Step 6: Commit**

```bash
git add .gitignore web/console-share/wasm web/console-share/build_wasm.sh web/console-share/vendor
git commit -m "build(web): add pinned Tailcat browser dialer"
```

### Task 8: Connect Tailcat to xterm.js in a static page

**Files:**

- Create: `web/console-share/index.html`
- Create: `web/console-share/app.js`
- Create: `web/console-share/ui.css`
- Create: `web/console-share/test/app.test.js`
- Copy: `src/old_sun_mcp/static/xterm.js` to `web/console-share/vendor/xterm.js`
- Copy: `src/old_sun_mcp/static/xterm.css` to `web/console-share/vendor/xterm.css`
- Copy: `src/old_sun_mcp/static/XTERM-LICENSE` to `web/console-share/vendor/XTERM-LICENSE`

**Step 1: Write browser-state tests**

With a fake `tailcatDial`, test address validation, connect, read loop, terminal
input, disconnect, occupied/EOF behavior, disabled input outside the connected
state, and explicit reconnect. Assert that the address never appears in
`location`, cookies, local storage, or session storage.

**Step 2: Run the tests and verify failure**

Run the selected browser test command from `web/console-share`.

Expected: FAIL because the page controller does not exist.

**Step 3: Implement the static UI**

Load Tailcat WebAssembly with progress reporting. Keep the entered address in a
module-local variable and clear the input after connection. Call
`tailcatDial({addr, derpMapURL, port: 1})`. Feed `conn.read()` results to
xterm.js until EOF, and send encoded terminal input with `conn.write()`.
Disable analytics and third-party scripts. Use bounded xterm.js scrollback.

**Step 4: Add restrictive static-site policy**

Document required HTTP headers: no-store caching for HTML, a content security
policy limited to self plus the configured DERP WebSocket endpoints, no
referrer, no framing, and no MIME sniffing. Keep all executable assets
same-origin.

**Step 5: Run the browser-state tests**

Expected: PASS.

**Step 6: Commit**

```bash
git add web/console-share
git commit -m "feat(web): connect xterm directly through Tailcat WebAssembly"
```

### Task 9: Prove browser and MCP behavior

**Files:**

- Create: `relay/integration/browser_test.go`
- Create: `relay/integration/testdata/derpmap.json`
- Create: `relay/integration/testdata/static_server.go`

**Step 1: Write the end-to-end test**

Start a local DERP fixture, a fake Unix console, the helper, and a static file
server that records every request. Launch headless Chromium, enter the helper
address, and assert byte-exact input and output through xterm.js. Disconnect
the browser, attach the MCP to the same address, and prove its read and write
path against the fake console.

**Step 2: Add privacy assertions**

Assert that the static server request log contains only expected asset paths.
It must contain no Tailcat address, console bytes, query string, POST, beacon,
or error-report request. Reload and prove the address field is empty.

**Step 3: Add ownership and cleanup assertions**

Open a second browser and prove it cannot obtain the active stream. Prove that
the MCP is also rejected while the first browser owns it. Disconnect the first,
attach the MCP, and prove that a browser is rejected while the MCP owns the
stream. Detach the MCP, connect the second browser, and prove it can use the
stream. Stop the helper and prove that its address no longer connects and all
test processes and sockets are gone.

**Step 4: Run the integration test**

Run: `cd relay && go test ./integration -run TestTailcatConsole -v -timeout 90s`

Expected: PASS on a host with the documented Chromium dependency. The portable
unit suite must skip this test with a precise prerequisite message when the
browser is absent.

**Step 5: Commit**

```bash
git add relay/integration
git commit -m "test(relay): prove browser and MCP console data flow"
```

### Task 10: Package, document, and validate a live console

**Files:**

- Create: `docs/TAILCAT-CONSOLE.md`
- Create: `docs/live-validation/YYYY-MM-DD-tailcat-console.md`
- Modify: `README.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `TODO.md`
- Modify: `SPEC.md`
- Modify: `.github/workflows/test.yml` if present, otherwise create the matching workflow file
- Operator-private: deploy the built static artifact at `https://console.unix.wtf/`

**Step 1: Document installation and use**

Cover publisher installation, both socket modes, token handling, one-consumer
ownership, browser DERP transport, MCP runtime attach and detach, public relay
limitations, supported hosts, and cleanup. State that the static server never
carries console traffic and that provisioning remains independent.

Document `https://console.unix.wtf/` as the canonical browser entry point.
Keep its host, DNS, proxy, certificate, release, and rollback details in the
ignored operator runbook rather than the portable project documentation.

**Step 2: Add CI jobs**

Run Python tests, Go unit tests with the race detector where supported,
WebAssembly build verification, license checks, and browser tests on the chosen
CI host. Pin toolchain and Tailcat versions.

**Step 3: Run portable verification**

Run:

```bash
uv run pytest -q
cd relay && go test -race ./...
git diff --check
```

Expected: every command passes.

**Step 4: Run opt-in live validation**

Use a disposable or snapshotted QEMU run. Record the exact socket, publisher
and bundled-client digests, Tailcat version, DERP map, browser version, browser
and MCP byte flow, cross-client exclusion, publisher shutdown, stale-address
failure, and socket cleanup. Do not use guest networking as a prerequisite.

Deploy the tested static artifact to `https://console.unix.wtf/` using the
operator-private runbook. Repeat the browser path from that origin and inspect
its access logs to prove they contain only expected static asset requests, not
the Tailcat address or console bytes.

**Step 5: Close the backlog item**

Move SUN-004 to History only after every acceptance criterion passes. Record
the completion date, commit or PR, validation document, and remaining source
discovery work under new TODO IDs.

**Step 6: Commit**

```bash
git add README.md SPEC.md TODO.md docs .github
git commit -m "docs(relay): document and validate Tailcat console transport"
```
