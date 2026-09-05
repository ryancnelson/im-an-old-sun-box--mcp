# Console build, test, and deployment

Biggie Woodpecker owns delivery for the GitHub repository:
`http://biggie.lynx-eagle.ts.net:8110/repos/7`.
The old RCN webhook subscriptions are disabled, not deleted.

The agent uses its existing SSH connection to Biggie. Darwin jobs continue
from Biggie to Minnie's verified Tailscale address `100.87.104.29`, with
`HostKeyAlias=minnie-2-2` retaining host-key verification. This does not rely
on MagicDNS in the agent container. The Tailscale FQDN is
`minnie-2-2.lynx-eagle.ts.net`; `minnie.lynx-eagle.ts.net` is not this host.

`.woodpecker/test.yml` runs Linux amd64 and Darwin arm64 tests, builds wheels,
installs those wheels over the editable checkouts, and reruns Python tests.
Both hosts need Python 3.11+, Node 18+, socat, Git, and SSH. The runner
bootstraps uv 0.9.22 and uses the checked-in lockfile. The optional illumos
test requires its explicit manual branch; ordinary pushes do not run it.

Each SHA has its own checkout and lock under `~/.cache/old-sun-console-ci/`.
The developer checkout is never overwritten. Test/build success markers must
match the exact SHA. Deployment is gated to main in Woodpecker and also
checks GitHub's current main SHA before restarting anything.

On Minnie, the owner-created file
`~/.local/state/old-sun-console/deployment.json` names the exact tmux pane,
working directory, operator-state file, and control socket. The deployed
wheel's launcher reuses the private credentials and operator selection.
Only the broker process is restarted; no guest input or VM restart occurs.
`/healthz` must report the expected revision; failed startup restores the
previous pane command. Successful deployment writes a private
`deployment-result.json`. Old release checkouts remain for recovery.

## Connection verification and limits

Inventory is not proof of a usable connection. Native socat and container
Python relays report readiness; their bounded error diagnostics reach the
browser. Selecting a target says *selected*, not *connected*. Docker's TTY
mode gets a raw no-echo PTY while the SSH link remains a byte stream, with
signal forwarding disabled. Containers with Unix sockets need Python 3,
not socat. Integration tests cover CR/LF, NUL, non-UTF8, and Ctrl-C bytes
against isolated fake consoles, not the lab guests.

On the live lab, ec2trib's socket was held by socat PID 35316 in another
tmux session. With Ryan's permission that client was detached; QEMU PID
35294 was not restarted. Biggie's Docker stdio and Niagara-playbox's Python
socket relay subsequently passed bounded live attachment checks without
guest input. ec2cicd CI-80 delivered console output. These checks do not
prove a guest command round-trip or guarantee that a later pipeline guest
will still be running.

The public Tailcat SPA and owner-only GitHub OAuth invitation service remain
separate backlog work. This deployment stays on loopback port 8877.
