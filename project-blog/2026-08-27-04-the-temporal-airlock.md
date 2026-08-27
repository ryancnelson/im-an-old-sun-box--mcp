# The temporal airlock has a modem prompt

*August 27, 2026*

I built a dial-up BBS for my emulated Solaris machine. It gives the guest a
reliable way to ask questions, fetch files, and start a network connection even
when its normal networking is broken.

A fresh Solaris installation may have no Bash, SSH, curl, working DNS, useful
compiler, or Python. That is especially painful when I am developing the
emulated network device. The BBS runs over a virtual channel between the guest
and host, so it does not depend on that device.

From Solaris, it looks like this:

```text
ATDT18005551212
CONNECT 2400

isp> ASK which library has nanosleep on Solaris 10
isp> GET libiconv sparc solaris 8
isp> STARTPPP
```

## `ASK`

The oracle runs on the host and knows the guest's actual constraints: Solaris
10 on SPARC, Bourne shell, non-GNU tools, old GNU Make, known library paths, and
the image's libc symbol-version ceiling. I can ask why a link failed before the
guest has enough networking to reach a current model itself.

The code includes a mode for small local models, but the minimum useful model
size is an observed constraint. I tested SmolLM2-135M-Instruct-Q4_K_M. When I
asked which library provides `nanosleep`, it invented `libniosleep`, fabricated
a documentation quote, and entered a repetition loop. A person using a 2005
Solaris image cannot cheaply verify that answer. The small-model prompt tells
the model to refuse Solaris-specific questions, and the source records why.

## `GET`

The host fetches a requested artifact with current DNS, TLS, and HTTP support,
then places it in a guest-visible delivery directory.

The first implementation delivered a 345-byte HTML error page as a compressed
package because curl returned success. The current code checks the HTTP status,
uses curl's fail-on-error mode, examines the downloaded file's magic bytes,
rejects suspicious HTML or tiny responses, and reports the size and checksum.
That 345-byte file is now a regression requirement.

## `STARTPPP`

The connection begins as a character terminal with a Hayes-style dial sequence.
After the guest sends `STARTPPP`, both sides hand the same file descriptor to
`pppd`. The BBS session becomes an IP link without a matching command from the
host operator.

The guest dialer is Perl because Solaris 10 already has Perl 5.8.4 with
Unix-domain socket support. It keeps one receive buffer across protocol waits.
`CONNECT`, the banner, and the `isp>` prompt can arrive in one read; an earlier
version discarded bytes between waits and then blocked waiting for text it had
already received.

## The MCP connection

The BBS is usable from inside Solaris with the base tools already present. The
MCP runs outside the guest and provides structured access to QEMU, GDB, host
tracing, run artifacts, and the evidence ledger. Both use the out-of-band
channel while serving different operators.

They can share services later. An MCP operation could place a verified build in
the BBS delivery directory. A BBS request could create an evidence event or ask
the host to inspect the channel bridge. `STARTPPP` could trigger synchronized
captures in Solaris, QEMU, and the host.

The BBS must continue to work without the MCP. Its value comes from the small
set of assumptions required to reach it. When the guest network is broken, the
fallback still answers `ATDT`.
