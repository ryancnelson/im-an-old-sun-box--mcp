"""Small serialized QEMU human-monitor protocol client."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import socket
import threading
from typing import Any

from .envelope import truncate_text
from .errors import OldSunError


_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
QUERY_PREFIXES = ("info ", "help", "query-", "x/")
CONTROLS = {"stop": "reversible", "cont": "reversible", "system_reset": "disruptive", "sendkey": "disruptive", "gdbserver": "disruptive"}


def validate_query(command: str) -> str:
    normalized = command.strip()
    if not normalized or "\n" in normalized or not normalized.startswith(QUERY_PREFIXES):
        raise OldSunError("INVALID_ARGUMENT", "HMP command is not an allowed query; use qemu.hmp_control for deliberate controls")
    return normalized


def classify_control(command: str) -> str:
    normalized = command.strip()
    first = normalized.split(maxsplit=1)[0] if normalized else ""
    if first not in CONTROLS:
        raise OldSunError("INVALID_ARGUMENT", "HMP control is not in the explicit allowlist", {"command": first})
    if "\n" in normalized:
        raise OldSunError("INVALID_ARGUMENT", "HMP commands must be one line")
    return CONTROLS[first]


def _read_prompt(client: socket.socket, max_bytes: int) -> bytes:
    data = bytearray()
    while not data.endswith(b"(qemu) "):
        chunk = client.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes + 4096:
            break
    return bytes(data)


def hmp_request(path: Path, command: str, timeout: float, max_bytes: int) -> dict[str, Any]:
    if not path.exists():
        raise OldSunError("SOCKET_CONNECT_FAILED", "QEMU monitor socket is missing", {"ref": path.name})
    try:
        with _locks[str(path)]:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(timeout); client.connect(str(path)); _read_prompt(client, max_bytes)
                client.sendall(command.encode("utf-8") + b"\n")
                raw = _read_prompt(client, max_bytes)
    except socket.timeout as exc:
        raise OldSunError("SOCKET_TIMEOUT", "QEMU monitor timed out", {"ref": path.name}) from exc
    except OSError as exc:
        raise OldSunError("SOCKET_CONNECT_FAILED", f"QEMU monitor failed: {exc}", {"ref": path.name}) from exc
    text = raw.decode("utf-8", errors="replace")
    if text.endswith("(qemu) "):
        text = text[:-7]
    bounded, warning = truncate_text(text.strip("\r\n"), max_bytes)
    return {"response": bounded, "warnings": [warning] if warning else []}
