# Pipeline console discovery (SUN-016)

## Contract

Every live, attachable console launched by the configured Woodpecker execution
hosts appears in localhost:8877 without restarting the web service or manually
refreshing its dropdowns. Discovery never opens a console or changes the active
target. CI cleanup removes a stopped guest from subsequent discovery. A console
used exclusively by a test remains owned by that test until it disconnects.

The first implementation uses the existing trusted host registry. Native QEMU
processes and Docker-contained QEMU processes are discovery providers feeding
the same ConsoleTarget model. Docker discovery is opt-in per host, constrained
by container-name prefixes and container-local socket roots. It reads exact
process argv and verifies socket existence without connecting. Selection and
every reconnect revalidate instance identity. Container ID and start time join
the QEMU process and socket identity; a restarted container is a new target.
Interactive Docker terminals are a separate `docker-stdio` endpoint. They are
listed only when the live QEMU is the container's main process, Docker stdin
and TTY are enabled, and QEMU explicitly uses serial stdio. Attach disables
Docker signal forwarding and detach-key interception. This is shared Docker
terminal access, not a claim of exclusive ownership against external clients.

Configured native roots include the run directories used by the checked-in
Niagara and Tribblix pipelines. Docker covers the OCI appliance and sun4u lanes,
including volume-backed /state sockets and /run/sun4u sockets which cannot be
resolved using host pathname rules. Host errors and Docker errors remain
separate so a failed provider does not hide healthy native targets.

The page polls after each completed discovery, with no overlapping requests.
Refreshing preserves the operator's pending host/console selection and never
attaches automatically. Unchanged failures do not flood terminal history.
Console listings have a display label and explicit transport metadata. A listed
console proves a live source and socket, not that its guest booted successfully.

## Alternatives

Polling the Woodpecker API for completed builds cannot prove a VM is still alive
and misses guests retained after pipeline completion. Posting registrations to
Minnie requires an inbound coordinator and credentials from each builder. Both
add lifecycle state that the execution host already supplies. Use live host
inventory now; allow a future signed publisher registration provider to feed the
same target descriptor without changing selection or terminal rendering.

## Public SPA and invitations

console.unix.wtf stays a static Go/WASM Tailcat client. It will not query SSH,
Docker, or Woodpecker. A publisher exports a separate versioned invitation with
run label, instance ID, Tailcat address, virtual port, issue time and expiry.
Pairing capabilities are never fields in the ordinary target inventory.

The owner selected GitHub OAuth restricted to their own account, superseding
the earlier SSH-key proof and encrypted-query proposal. Pin login `ryancnelson`
AND numeric GitHub user ID `347171` (verified from GitHub's public user API).
No SSH public or private key is needed. Anyone else's OAuth identity is denied
before receiving inventory, console metadata or invitation capabilities.

OAuth adds a small authentication/control service or access proxy to the static
asset host. It never carries terminal bytes: Tailcat still runs in browser WASM.
Builders may register a short-lived invitation with that authenticated service
and print `https://console.unix.wtf/?session=<opaque-id>`. After owner login, an
authorized redemption returns the Tailcat capability with Cache-Control: no-store.
The opaque session ID is not sufficient authorization. Expired, stopped or
replaced publisher instances cannot be redeemed. Builder registration uses a
separate scoped credential, never the owner's browser cookie or OAuth secret.
This is the implementation direction for SUN-017, not an API shipped by SUN-016.

Preserve only validated same-origin return paths across OAuth. Use state tokens,
secure HttpOnly cookies, CSRF protection, Referrer-Policy: no-referrer, no third
party scripts and no capability logging. The browser connects automatically only
after successful owner authorization and strict invitation validation. Raw tc
codes never appear in query strings. No URL may select a shell command, local
filename, or executable endpoint.

## Acceptance and delivery

TDD covers opt-in/allowlists; nested-container socket discovery; malformed,
stopped and restarted records; preservation of native results on Docker failure;
safe connector argv; identity revalidation; and automatic dropdown refresh that
preserves selection. Fake subprocess and filesystem fixtures run offline. An
opt-in live inventory verifies the current lab and the running localhost API.
No guest input is sent during discovery verification. Existing VM cleanup and
pipeline build-target matrices are unchanged.

The browser invitation implementation is a separate SUN-017 milestone. This
feature defines the boundary and does not claim to ship Tailcat WASM or live
OAuth deep links.
