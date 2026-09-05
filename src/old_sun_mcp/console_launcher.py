"""Persistent loopback development launcher; never prints credentials."""

import argparse
import json
import os
from pathlib import Path
import secrets
import stat

from .console_discovery import parse_hosts_json


def credentials(path: Path) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("credential handoff must be an owner-private regular file")
    else:
        with os.fdopen(fd, "w") as stream:
            json.dump({"mcp_token": secrets.token_hex(32), "session_secret": secrets.token_hex(32)}, stream)
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or len(value[k]) < 32
                                         for k in ("mcp_token", "session_secret")):
        raise ValueError("invalid private credential handoff")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--runtime-dir", type=Path, default=Path.home() / ".local/state/old-sun-console")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--control-socket", type=Path)
    args = parser.parse_args()
    hosts = args.hosts.read_text()
    parse_hosts_json(hosts)
    saved = credentials(args.runtime_dir / "credentials.json")
    os.environ.update({
        "OLD_SUN_CONSOLE_HOSTS_JSON": hosts,
        "OLD_SUN_CONSOLE_BIND": "127.0.0.1",
        "OLD_SUN_CONSOLE_PORT": str(args.port),
        "OLD_SUN_CONSOLE_PUBLIC_URL": f"http://127.0.0.1:{args.port}",
        "OLD_SUN_CONSOLE_DEV_AUTH": "1",
        "OLD_SUN_CONSOLE_MCP_TOKEN": saved["mcp_token"],
        "OLD_SUN_CONSOLE_SESSION_SECRET": saved["session_secret"],
        "OLD_SUN_CONSOLE_STATE": str(args.state or args.runtime_dir / "operator-state.json"),
        "OLD_SUN_CONSOLE_CONTROL_SOCKET": str(args.control_socket or args.runtime_dir / "control.sock"),
    })
    for key in ("OLD_SUN_CONSOLE_SOCKET", "OLD_SUN_CONSOLE_ADAPTER_JSON"):
        os.environ.pop(key, None)
    from .console_web import main as run
    run()


if __name__ == "__main__":
    main()
