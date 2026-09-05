"""Read-only Linux Docker inventory, also executed over an existing SSH channel.

Only explicit container prefixes and socket roots are inspected. No container
environment, console bytes, or credential files are read.
"""

import json
from pathlib import Path, PurePosixPath
import subprocess
import sys


def command(*argv):
    result = subprocess.run(argv, capture_output=True, check=True, timeout=5)
    return result.stdout.decode("utf-8", "replace")


def candidate_paths(argv):
    for value in argv:
        if value.startswith("unix:"):
            yield value[5:].split(",", 1)[0]
        elif value.startswith("socket,"):
            for field in value.split(","):
                if field.startswith("path="):
                    yield field[5:]


def allowed(path, roots):
    p = PurePosixPath(path)
    return (p.is_absolute() and ".." not in p.parts
            and not any(c in path for c in ("\0", "\r", "\n", ","))
            and any(p == root or root in p.parents for root in roots))


def inventory(prefixes, roots):
    roots = tuple(PurePosixPath(root) for root in roots)
    containers = command("docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}")
    records = []
    for line in containers.splitlines()[:128]:
        cid, name = line.split(" ", 1)
        if not name.startswith(tuple(prefixes)):
            continue
        try:
            info = json.loads(command("docker", "inspect", "--format",
                '{"state":{{json .State}},"stdin":{{json .Config.OpenStdin}},"tty":{{json .Config.Tty}}}', cid))
            state = info["state"]
            if not state.get("Running"):
                continue
            pids = command("docker", "top", cid, "-eo", "pid").splitlines()[1:]
            for raw_pid in pids[:128]:
                pid = int(raw_pid.strip())
                proc = Path("/proc") / str(pid)
                try:
                    argv = proc.joinpath("cmdline").read_bytes().decode("utf-8", "replace").rstrip("\0").split("\0")
                    if not PurePosixPath(argv[0]).name.startswith("qemu-system-"):
                        continue
                    started = proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
                    sockets = {}
                    for path in set(candidate_paths(argv)):
                        if not allowed(path, roots):
                            continue
                        try:
                            stat = command("docker", "exec", cid, "/bin/sh", "-c",
                                           'test -S "$1" && stat -Lc "%d %i %Y" -- "$1"', "console-stat", path)
                            device, inode, mtime = stat.split()
                            sockets[path] = {"device": int(device), "inode": int(inode), "mtime": float(mtime)}
                        except (subprocess.SubprocessError, ValueError):
                            continue
                    records.append({"container_id": cid, "container_name": name,
                                    "container_started_at": state["StartedAt"], "pid": pid,
                                    "started_at": started, "argv": argv, "sockets": sockets,
                                    "stdio": info["stdin"] is True and info["tty"] is True and state["Pid"] == pid})
                except (OSError, ValueError, IndexError):
                    continue  # A process may exit between top and inspection.
        except (subprocess.SubprocessError, ValueError, KeyError):
            continue  # A container may stop during inventory.
    return records


if __name__ == "__main__":
    try:
        print(json.dumps(inventory(json.loads(sys.argv[1]), json.loads(sys.argv[2]))))
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Docker inventory unavailable", file=sys.stderr)
        sys.exit(1)
