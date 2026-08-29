"""Authenticated local NDJSON control socket for MCP clients."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import asdict
import hmac
import json
import os
from pathlib import Path
import stat
from typing import Any

from .console_broker import ConsoleBroker, ConsoleUnavailable, McpWriteBlocked
from .console_discovery import ConsoleTarget
from .console_targets import ConsoleTargetManager


class ConsoleControlServer:
    def __init__(self, path: Path, token: str, broker: ConsoleBroker, *, lifecycle_adapter: tuple[str, ...] | None = None, target_manager: ConsoleTargetManager | None = None, max_line_bytes: int = 32_768):
        if not token:
            raise ValueError("control token is required")
        self.path = path
        self.token = token
        self.broker = broker
        self.lifecycle_adapter = lifecycle_adapter
        self.target_manager = target_manager
        self.max_line_bytes = max_line_bytes
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            mode = self.path.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(mode):
                raise RuntimeError("refusing to replace a non-socket control path")
            self.path.unlink()
        self._server = await asyncio.start_unix_server(self._handle, path=str(self.path))
        os.chmod(self.path, 0o660)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            mode = self.path.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISSOCK(mode):
                self.path.unlink()

    def _response(self, *, ok: bool, **values: Any) -> bytes:
        payload = {
            "ok": ok,
            **self.broker.snapshot(),
            "current_target": self.target_manager.snapshot() if self.target_manager is not None else None,
            **values,
        }
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @staticmethod
    def _target_payload(target: ConsoleTarget) -> dict[str, Any]:
        return {
            "target_id": target.target_id,
            "host_id": target.host_id,
            "socket_path": str(target.socket_path) if target.socket_path is not None else None,
            "endpoint": target.endpoint,
            "endpoint_kind": target.endpoint_kind,
            "pid": target.pid,
            "started_at": target.started_at,
            "command": target.command,
            "qemu_name": target.qemu_name,
            "socket_mtime": target.socket_mtime,
        }

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line or len(line) > self.max_line_bytes or not line.endswith(b"\n"):
                writer.write(self._response(ok=False, error="invalid_request"))
                return
            try:
                request = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                writer.write(self._response(ok=False, error="invalid_json"))
                return
            supplied = request.get("token", "") if isinstance(request, dict) else ""
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.token):
                writer.write(self._response(ok=False, error="unauthorized"))
                return
            operation = request.get("operation")
            if operation == "status":
                writer.write(self._response(ok=True))
            elif operation == "list_targets":
                if self.target_manager is None:
                    writer.write(self._response(ok=False, error="target_discovery_unavailable"))
                else:
                    report = await self.target_manager.discover()
                    writer.write(
                        self._response(
                            ok=True,
                            targets=[self._target_payload(target) for target in report.targets],
                            errors={host_id: asdict(error) for host_id, error in report.errors.items()},
                        )
                    )
            elif operation == "current_target":
                writer.write(self._response(ok=True))
            elif operation == "select_target":
                target_id = request.get("target_id")
                reason = request.get("reason")
                if not isinstance(target_id, str) or not target_id or not isinstance(reason, str) or not reason.strip():
                    writer.write(self._response(ok=False, error="invalid_argument"))
                elif self.target_manager is None:
                    writer.write(self._response(ok=False, error="target_discovery_unavailable"))
                else:
                    try:
                        await self.target_manager.select(target_id, actor="mcp")
                    except McpWriteBlocked:
                        writer.write(self._response(ok=False, error="write_blocked"))
                    except ValueError as exc:
                        error = "target_not_found" if str(exc).startswith("unknown") else "target_stale"
                        writer.write(self._response(ok=False, error=error, detail=str(exc)))
                    else:
                        writer.write(self._response(ok=True))
            elif operation == "read":
                writer.write(
                    self._response(
                        ok=True,
                        data_base64=base64.b64encode(self.broker.history.bytes()).decode("ascii"),
                    )
                )
            elif operation == "write":
                reason = request.get("reason")
                encoded = request.get("data_base64")
                if not isinstance(reason, str) or not reason.strip() or not isinstance(encoded, str):
                    writer.write(self._response(ok=False, error="invalid_argument"))
                else:
                    try:
                        data = base64.b64decode(encoded, validate=True)
                        await self.broker.write_mcp(data)
                    except (ValueError, binascii.Error):
                        writer.write(self._response(ok=False, error="invalid_argument"))
                    except McpWriteBlocked:
                        writer.write(self._response(ok=False, error="write_blocked"))
                    except ConsoleUnavailable:
                        writer.write(self._response(ok=False, error="console_unavailable"))
                    else:
                        writer.write(self._response(ok=True, bytes_written=len(data)))
            elif operation == "vm_control":
                action = request.get("action")
                reason = request.get("reason")
                if action not in {"break", "reset", "powerdown", "start"} or not isinstance(reason, str) or not reason.strip():
                    writer.write(self._response(ok=False, error="invalid_argument"))
                elif self.broker.state.mcp_write_blocked:
                    writer.write(self._response(ok=False, error="write_blocked"))
                elif (
                    self.target_manager.lifecycle_adapter() if self.target_manager is not None else self.lifecycle_adapter
                ) is None:
                    writer.write(self._response(ok=False, error="lifecycle_unavailable"))
                else:
                    lifecycle_adapter = (
                        self.target_manager.lifecycle_adapter()
                        if self.target_manager is not None
                        else self.lifecycle_adapter
                    )
                    process = await asyncio.create_subprocess_exec(
                        *(lifecycle_adapter or ()),
                        action,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                        writer.write(self._response(ok=False, error="lifecycle_timeout"))
                    else:
                        writer.write(
                            self._response(
                                ok=process.returncode == 0,
                                error=None if process.returncode == 0 else "lifecycle_failed",
                                action=action,
                                returncode=process.returncode,
                                output=stdout.decode("utf-8", "replace")[-4096:],
                                error_output=stderr.decode("utf-8", "replace")[-4096:],
                            )
                        )
            else:
                writer.write(self._response(ok=False, error="unknown_operation"))
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
