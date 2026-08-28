"""Single-owner QEMU serial console broker."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any

from .errors import OldSunError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new.{os.getpid()}.{secrets.token_hex(4)}")
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class ConsolePolicy:
    mcp_write_enabled: bool
    updated_at: str | None = None
    updated_by_id: int | None = None
    updated_by_login: str | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


class ConsolePolicyStore:
    """Durable human-owned policy. Invalid state fails closed."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> ConsolePolicy:
        if not self.path.exists():
            return ConsolePolicy(mcp_write_enabled=True)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("mcp_write_enabled"), bool):
                raise ValueError("mcp_write_enabled must be a boolean")
            actor_id = value.get("updated_by_id")
            actor_login = value.get("updated_by_login")
            updated_at = value.get("updated_at")
            if actor_id is not None and (isinstance(actor_id, bool) or not isinstance(actor_id, int)):
                raise ValueError("updated_by_id must be an integer")
            if actor_login is not None and not isinstance(actor_login, str):
                raise ValueError("updated_by_login must be a string")
            if updated_at is not None and not isinstance(updated_at, str):
                raise ValueError("updated_at must be a string")
            return ConsolePolicy(
                mcp_write_enabled=value["mcp_write_enabled"],
                updated_at=updated_at,
                updated_by_id=actor_id,
                updated_by_login=actor_login,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return ConsolePolicy(mcp_write_enabled=False, error=f"policy unreadable: {exc}")

    def set_mcp_write_enabled(self, enabled: bool, *, actor_id: int, actor_login: str) -> ConsolePolicy:
        if isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0:
            raise OldSunError("INVALID_ARGUMENT", "actor_id must be a positive integer")
        if not actor_login.strip():
            raise OldSunError("INVALID_ARGUMENT", "actor_login is required")
        policy = ConsolePolicy(
            mcp_write_enabled=bool(enabled),
            updated_at=_utc_now(),
            updated_by_id=actor_id,
            updated_by_login=actor_login,
        )
        try:
            _atomic_json(self.path, policy.public())
        except OSError as exc:
            raise OldSunError("CONSOLE_POLICY_WRITE_FAILED", f"Could not persist console policy: {exc}") from exc
        return policy


class ConsoleTranscript:
    """Bounded binary transcript with monotonic absolute byte cursors."""

    def __init__(self, path: Path, *, capacity_bytes: int = 1_048_576):
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self.path = path
        self.meta_path = path.with_name(f"{path.name}.cursor.json")
        self.capacity_bytes = capacity_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        self._base_cursor = self._load_base_cursor()

    def _load_base_cursor(self) -> int:
        if not self.meta_path.exists():
            return 0
        try:
            value = json.loads(self.meta_path.read_text(encoding="utf-8"))
            base = value["base_cursor"]
            if isinstance(base, bool) or not isinstance(base, int) or base < 0:
                raise ValueError("base_cursor must be a non-negative integer")
            return base
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise OldSunError("CONSOLE_TRANSCRIPT_INVALID", f"Transcript cursor metadata is invalid: {exc}") from exc

    @property
    def base_cursor(self) -> int:
        return self._base_cursor

    @property
    def cursor(self) -> int:
        return self._base_cursor + self.path.stat().st_size

    def append(self, data: bytes) -> tuple[int, int]:
        if not data:
            return self.cursor, self.cursor
        start = self.cursor
        try:
            with self.path.open("ab", buffering=0) as stream:
                stream.write(data)
                os.fsync(stream.fileno())
            end = start + len(data)
            size = self.path.stat().st_size
            if size > self.capacity_bytes:
                keep = self.capacity_bytes
                with self.path.open("rb") as stream:
                    stream.seek(-keep, os.SEEK_END)
                    retained = stream.read(keep)
                temporary = self.path.with_name(f".{self.path.name}.compact.{os.getpid()}")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(retained)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self._base_cursor = end - len(retained)
                _atomic_json(self.meta_path, {"base_cursor": self._base_cursor})
            return start, end
        except OSError as exc:
            raise OldSunError("CONSOLE_TRANSCRIPT_FAILED", f"Could not append console transcript: {exc}") from exc

    def read(self, after_cursor: int, max_bytes: int) -> dict[str, Any]:
        if isinstance(after_cursor, bool) or not isinstance(after_cursor, int) or after_cursor < 0:
            raise OldSunError("INVALID_ARGUMENT", "after_cursor must be a non-negative integer")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise OldSunError("INVALID_ARGUMENT", "max_bytes must be a positive integer")
        end = self.cursor
        start = max(self._base_cursor, min(after_cursor, end))
        count = min(max_bytes, end - start)
        try:
            with self.path.open("rb") as stream:
                stream.seek(start - self._base_cursor)
                data = stream.read(count)
        except OSError as exc:
            raise OldSunError("CONSOLE_TRANSCRIPT_FAILED", f"Could not read console transcript: {exc}") from exc
        return {
            "data": data,
            "base_cursor": self._base_cursor,
            "requested_cursor": after_cursor,
            "next_cursor": start + len(data),
            "end_cursor": end,
            "gap": after_cursor < self._base_cursor,
            "more": start + len(data) < end,
        }


class InputPriority(IntEnum):
    HUMAN = 0
    MCP = 10


@dataclass(order=True)
class QueuedInput:
    priority: int
    sequence: int
    data: bytes = field(compare=False)
    source: str = field(compare=False)
    reason: str | None = field(compare=False, default=None)


class ConsoleInputQueue:
    def __init__(self, max_items: int = 256):
        self._queue: asyncio.PriorityQueue[QueuedInput] = asyncio.PriorityQueue(maxsize=max_items)
        self._sequence = 0

    async def put(self, priority: InputPriority, data: bytes, source: str, reason: str | None = None) -> None:
        self._sequence += 1
        try:
            self._queue.put_nowait(QueuedInput(int(priority), self._sequence, data, source, reason))
        except asyncio.QueueFull as exc:
            raise OldSunError("CONSOLE_INPUT_QUEUE_FULL", "Console input queue is full") from exc

    async def get(self) -> QueuedInput:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()


@dataclass
class ConsoleLease:
    lease_id: str
    owner: str
    reason: str
    acquired_monotonic: float
    expires_monotonic: float

    def public(self) -> dict[str, Any]:
        remaining = max(0.0, self.expires_monotonic - time.monotonic())
        return {
            "lease_id": self.lease_id,
            "owner": self.owner,
            "reason": self.reason,
            "expires_in_seconds": remaining,
        }


class ConsoleBroker:
    """Owns one QEMU console connection and arbitrates all input."""

    KEY_BYTES = {
        "ctrl-c": b"\x03",
        "ctrl-d": b"\x04",
        "enter": b"\r",
        "escape": b"\x1b",
        "tab": b"\t",
    }

    def __init__(
        self,
        *,
        console_socket: Path,
        transcript: ConsoleTranscript,
        policy_store: ConsolePolicyStore,
        reconnect_seconds: float = 0.5,
        max_input_bytes: int = 4096,
        max_read_bytes: int = 262_144,
        audit_path: Path | None = None,
        run_id: str | None = None,
    ):
        self.console_socket = console_socket
        self.transcript = transcript
        self.policy_store = policy_store
        self.reconnect_seconds = reconnect_seconds
        self.max_input_bytes = max_input_bytes
        self.max_read_bytes = max_read_bytes
        self.audit_path = audit_path or transcript.path.with_name("console-input.jsonl")
        self.run_id = run_id or console_socket.parent.name
        self._input_queue = ConsoleInputQueue()
        self._connected = asyncio.Event()
        self._stopping = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._connection_task: asyncio.Task[None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._output_condition = asyncio.Condition()
        self._lease_lock = asyncio.Lock()
        self._lease: ConsoleLease | None = None
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self._last_connection_error: str | None = None

    async def start(self) -> None:
        if self._connection_task is not None:
            return
        self._stopping.clear()
        self._connection_task = asyncio.create_task(self._connection_loop(), name="console-connection")
        self._writer_task = asyncio.create_task(self._writer_loop(), name="console-writer")

    async def stop(self) -> None:
        self._stopping.set()
        tasks = [task for task in (self._connection_task, self._writer_task) if task is not None]
        for task in tasks:
            task.cancel()
        writer = self._writer
        self._writer = None
        self._connected.clear()
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connection_task = None
        self._writer_task = None

    async def _connection_loop(self) -> None:
        while not self._stopping.is_set():
            writer: asyncio.StreamWriter | None = None
            try:
                reader, writer = await asyncio.open_unix_connection(str(self.console_socket))
                self._writer = writer
                self._last_connection_error = None
                self._connected.set()
                await self._publish({"type": "status", "status": self.status()})
                while not self._stopping.is_set():
                    data = await reader.read(8192)
                    if not data:
                        raise ConnectionError("console socket closed")
                    start, end = self.transcript.append(data)
                    await self._publish({"type": "output", "data": data, "start_cursor": start, "next_cursor": end})
                    async with self._output_condition:
                        self._output_condition.notify_all()
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionError, OldSunError) as exc:
                self._last_connection_error = str(exc)
            finally:
                if self._writer is writer:
                    self._writer = None
                    self._connected.clear()
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
                await self._publish({"type": "status", "status": self.status()})
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.reconnect_seconds)
            except asyncio.TimeoutError:
                pass

    async def _writer_loop(self) -> None:
        while not self._stopping.is_set():
            item = await self._input_queue.get()
            try:
                await self._connected.wait()
                writer = self._writer
                if writer is None:
                    raise ConnectionError("console disconnected before write")
                writer.write(item.data)
                await writer.drain()
                self._record_input(item)
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionError) as exc:
                self._last_connection_error = str(exc)
            finally:
                self._input_queue.task_done()

    def _record_input(self, item: QueuedInput) -> None:
        value = {
            "observed_at": _utc_now(),
            "source": item.source,
            "reason": item.reason,
            "bytes": len(item.data),
            "sha256": hashlib.sha256(item.data).hexdigest(),
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
        except OSError as exc:
            self._last_connection_error = f"input audit failed: {exc}"

    async def _publish(self, event: dict[str, Any]) -> None:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._listeners:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._listeners.discard(queue)

    def subscribe(self, max_events: int = 128) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_events)
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._listeners.discard(queue)

    def read(self, after_cursor: int, max_bytes: int) -> dict[str, Any]:
        return self.transcript.read(after_cursor, min(max_bytes, self.max_read_bytes))

    async def expect(self, pattern: bytes, *, after_cursor: int, timeout_seconds: float) -> dict[str, Any]:
        if not pattern:
            raise OldSunError("INVALID_ARGUMENT", "expect pattern must not be empty")
        if len(pattern) > 4096:
            raise OldSunError("OUTPUT_LIMIT", "expect pattern exceeds 4096 bytes")
        deadline = time.monotonic() + timeout_seconds
        cursor = after_cursor
        carry = b""
        while True:
            result = self.read(cursor, self.max_read_bytes)
            data = result["data"]
            combined = carry + data
            index = combined.find(pattern)
            if index >= 0:
                match_end = result["next_cursor"] - len(data) - len(carry) + index + len(pattern)
                return {"matched": True, "match_end_cursor": match_end, **result}
            cursor = result["next_cursor"]
            carry = combined[-max(0, len(pattern) - 1) :]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OldSunError("SOCKET_TIMEOUT", "Console expect timed out", {"cursor": cursor})
            async with self._output_condition:
                try:
                    await asyncio.wait_for(self._output_condition.wait(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise OldSunError("SOCKET_TIMEOUT", "Console expect timed out", {"cursor": cursor}) from exc

    def _active_lease(self) -> ConsoleLease | None:
        if self._lease is not None and self._lease.expires_monotonic <= time.monotonic():
            self._lease = None
        return self._lease

    async def acquire(self, owner: str, reason: str, *, ttl_seconds: float) -> dict[str, Any]:
        if not owner.strip() or not reason.strip():
            raise OldSunError("INVALID_ARGUMENT", "Console lease owner and reason are required")
        if ttl_seconds <= 0 or ttl_seconds > 300:
            raise OldSunError("INVALID_ARGUMENT", "Console lease TTL must be between 0 and 300 seconds")
        async with self._lease_lock:
            active = self._active_lease()
            if active is not None:
                raise OldSunError("CONSOLE_LEASE_HELD", "Another MCP console lease is active", active.public())
            now = time.monotonic()
            self._lease = ConsoleLease(secrets.token_urlsafe(24), owner, reason, now, now + ttl_seconds)
            result = self._lease.public()
        await self._publish({"type": "status", "status": self.status()})
        return result

    def _verify_lease(self, lease_id: str) -> ConsoleLease:
        active = self._active_lease()
        if active is None:
            raise OldSunError("CONSOLE_LEASE_REQUIRED", "An active MCP console lease is required")
        if not secrets.compare_digest(active.lease_id, lease_id):
            raise OldSunError("CONSOLE_LEASE_INVALID", "The MCP console lease is invalid")
        return active

    async def release(self, lease_id: str) -> bool:
        async with self._lease_lock:
            active = self._active_lease()
            if active is None or not secrets.compare_digest(active.lease_id, lease_id):
                return False
            self._lease = None
        await self._publish({"type": "status", "status": self.status()})
        return True

    def _bounded_input(self, data: bytes) -> None:
        if not data:
            raise OldSunError("INVALID_ARGUMENT", "Console input must not be empty")
        if len(data) > self.max_input_bytes:
            raise OldSunError("OUTPUT_LIMIT", f"Console input exceeds {self.max_input_bytes} bytes")

    async def queue_human_input(self, data: bytes) -> dict[str, Any]:
        self._bounded_input(data)
        await self._input_queue.put(InputPriority.HUMAN, data, "human")
        return {"queued": len(data), "priority": "human"}

    async def queue_mcp_input(self, lease_id: str, data: bytes, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise OldSunError("INVALID_ARGUMENT", "A non-empty reason is required for MCP console input")
        self._bounded_input(data)
        policy = self.policy_store.load()
        if not policy.mcp_write_enabled:
            raise OldSunError("CONSOLE_POLICY_BLOCKED", "Human policy currently blocks MCP console writes", policy.public())
        self._verify_lease(lease_id)
        if not self._connected.is_set():
            raise OldSunError("CONSOLE_OFFLINE", "The QEMU console is not connected")
        await self._input_queue.put(InputPriority.MCP, data, "mcp", reason)
        return {"queued": len(data), "priority": "mcp", "cursor_at_queue": self.transcript.cursor}

    async def send_mcp_key(self, lease_id: str, key: str, reason: str) -> dict[str, Any]:
        data = self.KEY_BYTES.get(key.lower())
        if data is None:
            raise OldSunError("INVALID_ARGUMENT", f"Unsupported console key: {key}")
        result = await self.queue_mcp_input(lease_id, data, reason)
        result["key"] = key.lower()
        return result

    def status(self) -> dict[str, Any]:
        active = self._active_lease()
        return {
            "run": self.run_id,
            "console_connected": self._connected.is_set(),
            "console_socket": self.console_socket.name,
            "cursor": self.transcript.cursor,
            "base_cursor": self.transcript.base_cursor,
            "queued_inputs": self._input_queue.qsize(),
            "human_clients": len(self._listeners),
            "mcp_lease": active.public() if active else None,
            "policy": self.policy_store.load().public(),
            "last_connection_error": self._last_connection_error,
        }

    async def set_mcp_write_enabled(self, enabled: bool, *, actor_id: int, actor_login: str) -> dict[str, Any]:
        policy = self.policy_store.set_mcp_write_enabled(enabled, actor_id=actor_id, actor_login=actor_login)
        await self._publish({"type": "status", "status": self.status()})
        return policy.public()
