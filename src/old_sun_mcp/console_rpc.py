"""Authenticated JSON-lines RPC between MCP and the console broker."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
from pathlib import Path
import secrets
import socket
import stat
from typing import Any
import uuid

from .console_broker import ConsoleBroker
from .errors import OldSunError


def _encode_binary(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "data_base64": base64.b64encode(value).decode("ascii"),
            "text": value.decode("utf-8", errors="replace"),
        }
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "data" and isinstance(item, bytes):
                result.update(_encode_binary(item))
            else:
                result[key] = _encode_binary(item)
        return result
    if isinstance(value, list):
        return [_encode_binary(item) for item in value]
    return value


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise OldSunError("INVALID_ARGUMENT", f"{name} must be between 1 and {maximum}")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OldSunError("INVALID_ARGUMENT", f"{name} must be a non-negative integer")
    return value


class ConsoleRpcServer:
    def __init__(self, path: Path, token: str, broker: ConsoleBroker, *, max_request_bytes: int = 65_536):
        if not token:
            raise ValueError("RPC token must not be empty")
        self.path = path
        self.token = token
        self.broker = broker
        self.max_request_bytes = max_request_bytes
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if self._server is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = self.path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(current.st_mode):
                raise OldSunError("CONSOLE_RPC_PATH_UNSAFE", "Refusing to replace a non-socket RPC path")
            self.path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle,
            path=str(self.path),
            limit=self.max_request_bytes + 1,
        )
        os.chmod(self.path, 0o600)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            if stat.S_ISSOCK(self.path.lstat().st_mode):
                self.path.unlink()
        except FileNotFoundError:
            pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_id: Any = None
        try:
            line = await reader.readline()
            if not line or len(line) > self.max_request_bytes:
                raise OldSunError("OUTPUT_LIMIT", "Console RPC request exceeded its size limit")
            try:
                request = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OldSunError("INVALID_ARGUMENT", "Console RPC request is not valid JSON") from exc
            if not isinstance(request, dict):
                raise OldSunError("INVALID_ARGUMENT", "Console RPC request must be an object")
            request_id = request.get("id")
            supplied = request.get("token")
            if not isinstance(supplied, str) or not secrets.compare_digest(supplied, self.token):
                raise OldSunError("CONSOLE_RPC_UNAUTHORIZED", "Console RPC authentication failed")
            method = request.get("method")
            params = request.get("params", {})
            if not isinstance(method, str) or not isinstance(params, dict):
                raise OldSunError("INVALID_ARGUMENT", "Console RPC method and params are required")
            result = await self._dispatch(method, params)
            response = {"id": request_id, "ok": True, "result": _encode_binary(result)}
        except OldSunError as exc:
            response = {
                "id": request_id,
                "ok": False,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            }
        except Exception:
            response = {
                "id": request_id,
                "ok": False,
                "error": {"code": "INTERNAL_ERROR", "message": "Unexpected console RPC failure", "details": {}},
            }
        encoded = (json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8")
        writer.write(encoded)
        try:
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "status":
            return self.broker.status()
        if method == "read":
            return self.broker.read(
                _non_negative_int(params.get("after_cursor", 0), "after_cursor"),
                _positive_int(params.get("max_bytes", 65_536), "max_bytes", self.broker.max_read_bytes),
            )
        if method == "acquire":
            return await self.broker.acquire(
                str(params.get("owner", "")),
                str(params.get("reason", "")),
                ttl_seconds=float(params.get("ttl_seconds", 30)),
            )
        if method == "release":
            return {"released": await self.broker.release(str(params.get("lease_id", "")))}
        if method == "write":
            encoded = params.get("data_base64")
            if not isinstance(encoded, str):
                raise OldSunError("INVALID_ARGUMENT", "data_base64 is required")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise OldSunError("INVALID_ARGUMENT", "data_base64 is invalid") from exc
            return await self.broker.queue_mcp_input(
                str(params.get("lease_id", "")), data, str(params.get("reason", ""))
            )
        if method == "send_key":
            return await self.broker.send_mcp_key(
                str(params.get("lease_id", "")),
                str(params.get("key", "")),
                str(params.get("reason", "")),
            )
        if method == "expect":
            pattern = params.get("pattern")
            if not isinstance(pattern, str):
                raise OldSunError("INVALID_ARGUMENT", "expect pattern must be a string")
            return await self.broker.expect(
                pattern.encode("utf-8"),
                after_cursor=_non_negative_int(params.get("after_cursor", 0), "after_cursor"),
                timeout_seconds=float(params.get("timeout_seconds", 30)),
            )
        raise OldSunError("INVALID_ARGUMENT", f"Unknown console RPC method: {method}")


class ConsoleRpcClient:
    def __init__(self, path: Path, token: str, *, timeout_seconds: float, max_response_bytes: int = 1_048_576):
        self.path = path
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = uuid.uuid4().hex
        request = {
            "id": request_id,
            "token": self.token,
            "method": method,
            "params": params or {},
        }
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout_seconds)
                client.connect(str(self.path))
                client.sendall(payload)
                with client.makefile("rb") as stream:
                    line = stream.readline(self.max_response_bytes + 1)
        except socket.timeout as exc:
            raise OldSunError("SOCKET_TIMEOUT", "Console RPC timed out") from exc
        except OSError as exc:
            raise OldSunError("SOCKET_CONNECT_FAILED", f"Console RPC failed: {exc}", {"ref": self.path.name}) from exc
        if not line:
            raise OldSunError("SOCKET_CONNECT_FAILED", "Console RPC closed without a response")
        if len(line) > self.max_response_bytes:
            raise OldSunError("OUTPUT_LIMIT", "Console RPC response exceeded its size limit")
        try:
            response = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OldSunError("COMMAND_FAILED", "Console RPC returned malformed JSON") from exc
        if not isinstance(response, dict) or response.get("id") != request_id:
            raise OldSunError("COMMAND_FAILED", "Console RPC returned a mismatched response")
        if not response.get("ok"):
            error = response.get("error", {})
            raise OldSunError(
                str(error.get("code", "COMMAND_FAILED")),
                str(error.get("message", "Console RPC request failed")),
                error.get("details") if isinstance(error.get("details"), dict) else {},
            )
        return response.get("result")
