"""Persistent human-controlled console policy."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile


class OperatorState:
    """Store the MCP write block atomically and fail closed."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._mcp_write_blocked = True

    @property
    def mcp_write_blocked(self) -> bool:
        return self._mcp_write_blocked

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._mcp_write_blocked = True
            return
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._mcp_write_blocked = True
            return
        value = raw.get("mcp_write_blocked") if isinstance(raw, dict) else None
        self._mcp_write_blocked = value if isinstance(value, bool) else True

    async def set_mcp_write_blocked(self, blocked: bool) -> None:
        if not isinstance(blocked, bool):
            raise TypeError("blocked must be a bool")
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"mcp_write_blocked": blocked}, sort_keys=True) + "\n"
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
                self._mcp_write_blocked = blocked
            finally:
                if fd >= 0:
                    os.close(fd)
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def snapshot(self) -> dict[str, bool]:
        return {"mcp_write_blocked": self._mcp_write_blocked}
