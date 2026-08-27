# The Temporal Airlock Has a Modem Prompt

*August 27, 2026*

The spiritual ancestor of this MCP already exists in Ryan's
[`qemu-sun4v-illumos`](https://github.com/ryancnelson/qemu-sun4v-illumos)
repository. It is an old-school dial-up BBS running over a virtual channel
between a Solaris guest and its modern host.

This is not a decorative retro interface. It solves the bootstrap problem.

A freshly installed old Solaris machine may have no Bash, no SSH, no curl, no
working DNS, no useful compiler, and—when the emulated network device is the
thing being developed—no network connection at all. Historically, escaping
that hole meant carrying tools into the machine through increasingly absurd
mechanisms until it acquired enough capability to help itself.

The BBS gives the isolated guest one guaranteed something-out-there:

```text
ATDT18005551212
CONNECT 2400

isp> ASK which library has nanosleep on Solaris 10
isp> GET libiconv sparc solaris 8
isp> STARTPPP
```

Those three commands form a capability ladder.

`ASK` exports the knowledge problem. The oracle runs on the modern side and is
prompted with the guest's real constraints: Solaris 10 on SPARC, real Bourne
shell, non-GNU tools, old GNU Make, known library locations, and a specific libc
symbol-version ceiling. The person in the guest can ask a current model why a
link failed without first constructing enough internet to reach one.

The implementation also records an important negative result. A measured 135M
local model ignored instructions to admit uncertainty, invented a nonexistent
`libniosleep`, fabricated supporting documentation, and fell into a repetition
loop. At 2400 baud, on a machine where checking the answer is itself expensive,
a confident liar is worse than no oracle. The tiny-model mode therefore treats
honest ignorance as a feature, not a personality defect.

`GET` exports the acquisition problem. The host has modern DNS, TLS, HTTP, and
curl, so it fetches the requested artifact into a guest-visible delivery area.
But the BBS learned not to confuse transport success with a valid payload. An
early version cheerfully delivered a 345-byte HTML error page as a compressed
package because curl returned success. The current path checks HTTP status,
uses fail-on-error fetching, examines content magic, rejects suspicious tiny or
HTML responses, and reports size and checksum. This is scar-tissue engineering:
the code remembers the specific lie it was once told.

`STARTPPP` exports the networking bootstrap. The line begins as a character
terminal with Hayes-modem theater. When the guest asks, the host and guest hand
that same file descriptor to `pppd`, and the BBS line becomes an IP link. The
caller decides when networking begins. A guest reboot no longer requires a
human to notice and issue the matching host-side command at exactly the right
time.

The guest dialer is written in Perl because Solaris 10 already has Perl 5.8.4
with Unix-domain sockets and does not have Python. It uses one retained receive
buffer because `CONNECT`, the banner, and the `isp>` prompt can arrive in the
same read; an earlier implementation discarded already-received bytes between
waits and then waited forever for text it had thrown away. Again, the interface
is whimsical. The engineering is not.

## Two faces of one service plane

The BBS and this MCP approach the same problem from opposite centuries.

The BBS is the guest-native emergency door. It is line-oriented ASCII, usable
from inside the old machine with nearly nothing. When the guest network, modern
toolchain, and elaborate control software are all absent or suspect, `ATDT`,
`CONNECT 2400`, and a prompt remain understandable.

The MCP is the 2026 cockpit outside the machine. It provides structured run
identity, bounded tools, evidence provenance, hypotheses, QEMU monitor access,
SPARC debugging, guest DTrace, host eBPF/perf, artifact handling, and cleanup
proof.

The shared-disk channel between them is a temporal airlock. On one side stands
a Solaris administrator working with the capabilities of an old Sun box. On
the other side is a modern host with storage, networking, models, debuggers, and
enough compute to be extravagant. The airlock moves selected knowledge, files,
requests, and eventually packets between them without pretending the guest's
own broken network works.

These interfaces should eventually share services without sharing failure
domains. An MCP investigation could place a verified build artifact into the
BBS delivery area. A BBS distress request could become a sourced evidence event
or ask the host to examine its channel bridge. A `STARTPPP` transition could
trigger synchronized before-and-after observations inside Solaris, in QEMU,
and on the host.

But the BBS must remain independently useful. It is the bottom rung of the
capability ladder, not a novelty skin over the MCP. Sophisticated control planes
are wonderful right up until their prerequisites are the thing on fire.

That makes the Sunset BBS something better than nostalgia: an unusually good
reliability interface wearing a wonderfully ridiculous costume.
