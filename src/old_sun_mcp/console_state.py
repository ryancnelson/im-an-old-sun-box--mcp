"""Persistent human-controlled console policy."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class SelectedTargetIdentity:
    host_id: str
    endpoint: str
    pid: int
    started_at: str

    @classmethod
    def from_json(cls, value: object) -> "SelectedTargetIdentity":
        if not isinstance(value, dict):
            raise ValueError("invalid selected target")
        keys = set(value)
        legacy = keys == {"host_id", "socket_path", "pid", "started_at"}
        if not legacy and keys != {"host_id", "endpoint", "pid", "started_at"}:
            raise ValueError("invalid selected target")
        host_id = value["host_id"]
        endpoint = value["socket_path"] if legacy else value["endpoint"]
        pid = value["pid"]
        started_at = value["started_at"]
        if (
            not isinstance(host_id, str)
            or not host_id
            or not isinstance(endpoint, str)
            or not endpoint
            or isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or not isinstance(started_at, str)
            or not started_at
        ):
            raise ValueError("invalid selected target")
        return cls(host_id, endpoint, pid, started_at)


class OperatorState:
    """Store the MCP write block atomically and fail closed."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._mcp_write_blocked = True
        self._selected_target: SelectedTargetIdentity | None = None

    @property
    def mcp_write_blocked(self) -> bool:
        return self._mcp_write_blocked

    @property
    def selected_target(self) -> SelectedTargetIdentity | None:
        return self._selected_target

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._mcp_write_blocked = True
            self._selected_target = None
            return
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._mcp_write_blocked = True
            self._selected_target = None
            return
        if not isinstance(raw, dict):
            self._mcp_write_blocked = True
            self._selected_target = None
            return
        value = raw.get("mcp_write_blocked")
        try:
            selected = SelectedTargetIdentity.from_json(raw["selected_target"]) if "selected_target" in raw else None
        except ValueError:
            self._mcp_write_blocked = True
            self._selected_target = None
            return
        self._mcp_write_blocked = value if isinstance(value, bool) else True
        self._selected_target = selected

    def _payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"mcp_write_blocked": self._mcp_write_blocked}
        if self._selected_target is not None:
            payload["selected_target"] = asdict(self._selected_target)
        return payload

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._payload(), sort_keys=True) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    async def set_mcp_write_blocked(self, blocked: bool) -> None:
        if not isinstance(blocked, bool):
            raise TypeError("blocked must be a bool")
        async with self._lock:
            previous = self._mcp_write_blocked
            self._mcp_write_blocked = blocked
            try:
                self._persist()
            except Exception:
                self._mcp_write_blocked = previous
                raise

    async def set_selected_target(self, selected: SelectedTargetIdentity | None) -> None:
        if selected is not None and not isinstance(selected, SelectedTargetIdentity):
            raise TypeError("selected must be a SelectedTargetIdentity or None")
        async with self._lock:
            previous = self._selected_target
            self._selected_target = selected
            try:
                self._persist()
            except Exception:
                self._selected_target = previous
                raise

    def snapshot(self) -> dict[str, object]:
        return self._payload()
