"""Minimal typed QEMU Machine Protocol client."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import socket
import threading
from typing import Any

from .errors import OldSunError


_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


def _read_object(stream: Any, max_bytes: int) -> dict[str, Any]:
    line = stream.readline(max_bytes + 1)
    if not line:
        raise OldSunError("SOCKET_CONNECT_FAILED", "QMP closed before returning a response")
    if len(line) > max_bytes:
        raise OldSunError("OUTPUT_LIMIT", "QMP response exceeded the configured output limit")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OldSunError("COMMAND_FAILED", "QMP returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise OldSunError("COMMAND_FAILED", "QMP returned a non-object response")
    return value


def _send(stream: Any, value: dict[str, Any]) -> None:
    stream.write(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")
    stream.flush()


def _response(stream: Any, request_id: str, max_bytes: int) -> dict[str, Any]:
    while True:
        value = _read_object(stream, max_bytes)
        if value.get("id") != request_id:
            continue
        if "error" in value:
            error = value["error"]
            raise OldSunError("COMMAND_FAILED", "QMP command failed", {"qmp_error": error})
        if "return" not in value:
            raise OldSunError("COMMAND_FAILED", "QMP response omitted return data")
        return value["return"]


def qmp_request(
    path: Path,
    execute: str,
    timeout: float,
    max_bytes: int,
    arguments: dict[str, Any] | None = None,
) -> Any:
    if not path.exists():
        raise OldSunError("SOCKET_CONNECT_FAILED", "QMP socket is missing", {"ref": path.name})
    try:
        with _locks[str(path)]:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(timeout)
                client.connect(str(path))
                with client.makefile("rwb", buffering=0) as stream:
                    greeting = _read_object(stream, max_bytes)
                    if "QMP" not in greeting:
                        raise OldSunError("COMMAND_FAILED", "QMP greeting is missing")
                    _send(stream, {"execute": "qmp_capabilities", "id": "capabilities"})
                    _response(stream, "capabilities", max_bytes)
                    request: dict[str, Any] = {"execute": execute, "id": "request"}
                    if arguments:
                        request["arguments"] = arguments
                    _send(stream, request)
                    return _response(stream, "request", max_bytes)
    except socket.timeout as exc:
        raise OldSunError("SOCKET_TIMEOUT", "QMP socket timed out", {"ref": path.name}) from exc
    except OldSunError:
        raise
    except OSError as exc:
        raise OldSunError("SOCKET_CONNECT_FAILED", f"QMP socket failed: {exc}", {"ref": path.name}) from exc
