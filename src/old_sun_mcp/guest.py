"""Bounded out-of-band guest adapters."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from typing import Any

from .config import GuestAdapter
from .envelope import truncate_text
from .errors import OldSunError


def console_tail(run: Path, max_bytes: int) -> dict[str, Any]:
    path = run / "console.log"
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            stream.seek(max(0, size - max_bytes))
            data = stream.read(max_bytes)
    except OSError as exc:
        raise OldSunError("SOURCE_MISSING", "Console log is unavailable", {"ref": "console.log"}) from exc
    return {"text": data.decode("utf-8", errors="replace"), "returned_bytes": len(data), "original_bytes": size}


def _argv_guest(run: Path, adapter: GuestAdapter, command: str, timeout: float, max_bytes: int) -> dict[str, Any]:
    socket_path = run / adapter.socket
    replacements = {"{socket}": str(socket_path), "{command}": command, "{timeout}": str(timeout)}
    argv = [replacements.get(item, item) for item in adapter.argv]
    env = {name: os.environ[name] for name in adapter.env_allowlist if name in os.environ}
    started = time.monotonic()
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, shell=False, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OldSunError("COMMAND_TIMEOUT", "Guest adapter timed out; guest command termination is unknown", {"timeout_seconds": timeout}) from exc
    except OSError as exc:
        raise OldSunError("ADAPTER_UNAVAILABLE", f"Guest adapter could not start: {exc}") from exc
    stdout, stdout_warning = truncate_text(result.stdout, max_bytes)
    stderr, stderr_warning = truncate_text(result.stderr, max_bytes)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_status": result.returncode,
        "duration_seconds": time.monotonic() - started,
        "timed_out": False,
        "warnings": [warning for warning in (stdout_warning, stderr_warning) if warning],
    }


def _fresh_shell(run: Path, adapter: GuestAdapter, command: str, timeout: float, max_bytes: int) -> dict[str, Any]:
    path = run / adapter.socket
    marker = f"__OLD_SUN_{secrets.token_hex(12)}__"
    payload = f"{command}\nprintf '{marker}%s\\n' $?\n".encode()
    started = time.monotonic()
    data = bytearray()
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(timeout); client.connect(str(path)); client.sendall(payload)
            while marker.encode() not in data and len(data) <= max_bytes + 4096:
                chunk = client.recv(4096)
                if not chunk: break
                data.extend(chunk)
    except socket.timeout as exc:
        raise OldSunError("COMMAND_TIMEOUT", "Fresh guest shell timed out; command termination is unknown") from exc
    except OSError as exc:
        raise OldSunError("SOCKET_CONNECT_FAILED", f"Guest socket failed: {exc}", {"ref": adapter.socket}) from exc
    decoded = data.decode("utf-8", errors="replace")
    before, separator, after = decoded.partition(marker)
    if not separator:
        raise OldSunError("COMMAND_FAILED", "Fresh guest shell closed without a completion marker")
    try:
        status = int(after.strip().splitlines()[0])
    except (ValueError, IndexError) as exc:
        raise OldSunError("COMMAND_FAILED", "Fresh guest shell returned a malformed exit marker") from exc
    output, warning = truncate_text(before, max_bytes)
    return {"stdout": output, "stderr": "", "exit_status": status, "duration_seconds": time.monotonic() - started, "timed_out": False, "warnings": [warning] if warning else []}


def execute_guest(run: Path, adapter: GuestAdapter, command: str, timeout: float, max_bytes: int) -> dict[str, Any]:
    if not command.strip():
        raise OldSunError("INVALID_ARGUMENT", "command must not be empty")
    if timeout <= 0:
        raise OldSunError("INVALID_ARGUMENT", "timeout must be positive")
    if adapter.kind == "argv":
        return _argv_guest(run, adapter, command, timeout, max_bytes)
    if adapter.kind == "fresh-unix-shell":
        return _fresh_shell(run, adapter, command, timeout, max_bytes)
    raise OldSunError("ADAPTER_UNAVAILABLE", f"Unsupported guest adapter: {adapter.kind}")

