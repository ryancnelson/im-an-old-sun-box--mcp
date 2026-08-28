"""Synchronous MCP client for the broker's authenticated local socket."""

from __future__ import annotations

import json
import socket
from typing import Any

from .errors import OldSunError


ERROR_CODES = {
    "unauthorized": "CONSOLE_AUTH_FAILED",
    "write_blocked": "CONSOLE_WRITE_BLOCKED",
    "console_unavailable": "CONSOLE_UNAVAILABLE",
    "invalid_argument": "INVALID_ARGUMENT",
    "lifecycle_unavailable": "ADAPTER_UNAVAILABLE",
    "lifecycle_timeout": "TIMEOUT",
    "lifecycle_failed": "VM_CONTROL_FAILED",
}


def control_request(
    socket_path: str,
    token: str,
    request: dict[str, Any],
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    payload = {"token": token, **request}
    encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    if len(encoded) > max_bytes:
        raise OldSunError("OUTPUT_LIMIT", "Console control request exceeds the configured limit")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect(socket_path)
        client.sendall(encoded)
        chunks = bytearray()
        while b"\n" not in chunks:
            chunk = client.recv(min(4096, max_bytes + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > max_bytes:
                raise OldSunError("OUTPUT_LIMIT", "Console control response exceeds the configured limit")
    except TimeoutError as exc:
        raise OldSunError("TIMEOUT", "Console control request timed out") from exc
    except OSError as exc:
        raise OldSunError("CONSOLE_UNAVAILABLE", f"Console control socket failed: {exc}") from exc
    finally:
        client.close()
    try:
        response = json.loads(bytes(chunks).split(b"\n", 1)[0])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OldSunError("PROTOCOL_ERROR", "Console control returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise OldSunError("PROTOCOL_ERROR", "Console control returned a non-object")
    if not response.get("ok"):
        error = response.get("error", "console_error")
        code = ERROR_CODES.get(str(error), "CONSOLE_ERROR")
        raise OldSunError(
            code,
            f"Console control rejected the request: {error}",
            {
                "connected": response.get("connected"),
                "mcp_write_blocked": response.get("mcp_write_blocked"),
            },
        )
    response.pop("ok", None)
    return response
