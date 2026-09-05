"""Single-owner QEMU serial-console broker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from .console_state import OperatorState
from .console_transport import ConsoleConnector, ConsoleEndpoint, UnixConsoleConnector


class ConsoleUnavailable(RuntimeError):
    pass


class McpWriteBlocked(RuntimeError):
    pass


class BoundedHistory:
    def __init__(self, maximum: int):
        if maximum <= 0:
            raise ValueError("maximum must be positive")
        self.maximum = maximum
        self._data = bytearray()

    def append(self, data: bytes) -> None:
        self._data.extend(data)
        overflow = len(self._data) - self.maximum
        if overflow > 0:
            del self._data[:overflow]

    def bytes(self) -> bytes:
        return bytes(self._data)

    def clear(self) -> None:
        self._data.clear()


@dataclass(frozen=True)
class ConsoleEvent:
    kind: str
    data: bytes | None = None
    connected: bool | None = None
    mcp_write_blocked: bool | None = None
    target: dict[str, object] | None = None
    error: str | None = None


class ConsoleBroker:
    def __init__(
        self,
        transport: ConsoleConnector | Path | None,
        state: OperatorState,
        *,
        history_bytes: int = 262_144,
        retry_seconds: float = 0.25,
        max_write_bytes: int = 16_384,
    ):
        self.transport = UnixConsoleConnector(transport) if isinstance(transport, Path) else transport
        self.state = state
        self.history = BoundedHistory(history_bytes)
        self.retry_seconds = retry_seconds
        self.max_write_bytes = max_write_bytes
        self.connected = False
        self.error: str | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._replace_lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[ConsoleEvent]] = set()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self.state.load()
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._connect_loop(), name="qemu-console-broker")

    async def stop(self) -> None:
        self._stopping.set()
        await self._stop_connect_loop()
        self._set_connection(None)

    async def _stop_connect_loop(self) -> None:
        if self._writer is not None:
            self._writer.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def replace_transport(self, transport: ConsoleConnector | Path | None, *, clear_history: bool = True) -> None:
        replacement = UnixConsoleConnector(transport) if isinstance(transport, Path) else transport
        async with self._replace_lock:
            running = self._task is not None
            await self._stop_connect_loop()
            self._set_connection(None)
            self.transport = replacement
            self.error = None
            if clear_history:
                self.history.clear()
            if running:
                self._stopping.clear()
                self._task = asyncio.create_task(self._connect_loop(), name="qemu-console-broker")

    def broadcast_target(self, target: dict[str, object] | None) -> None:
        self._broadcast(ConsoleEvent("target", target=target))

    def snapshot(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "mcp_write_blocked": self.state.mcp_write_blocked,
            "history_bytes": len(self.history.bytes()),
            "error": self.error,
        }

    def subscribe(self) -> asyncio.Queue[ConsoleEvent]:
        queue: asyncio.Queue[ConsoleEvent] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ConsoleEvent]) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, event: ConsoleEvent) -> None:
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)

    def _set_connection(self, writer: asyncio.StreamWriter | None) -> None:
        self._writer = writer
        connected = writer is not None
        if connected:
            self.error = None
        if self.connected != connected:
            self.connected = connected
            self._broadcast(
                ConsoleEvent(
                    "status",
                    connected=connected,
                    mcp_write_blocked=self.state.mcp_write_blocked,
                    error=self.error,
                )
            )

    def _set_error(self, error: str) -> None:
        if self.error != error:
            self.error = error
            self._broadcast(ConsoleEvent("status", connected=False,
                                         mcp_write_blocked=self.state.mcp_write_blocked, error=error))

    async def _connect_loop(self) -> None:
        while not self._stopping.is_set():
            endpoint: ConsoleEndpoint | None = None
            try:
                if self.transport is None:
                    raise FileNotFoundError("no console target is selected")
                endpoint = await self.transport.connect()
                self._set_connection(endpoint.writer)
                while data := await endpoint.reader.read(4096):
                    self.history.append(data)
                    self._broadcast(ConsoleEvent("output", data=data))
                raise ConnectionError(endpoint.error_detail() or "Console stream closed")
            except ValueError as exc:
                # A changed target identity requires explicit selection again.
                self._set_error(str(exc))
                return
            except (FileNotFoundError, ConnectionError, OSError, RuntimeError) as exc:
                self._set_error(str(exc) or type(exc).__name__)
            finally:
                if endpoint is not None:
                    await endpoint.close()
                self._set_connection(None)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.retry_seconds)
            except TimeoutError:
                pass

    async def set_mcp_write_blocked(self, blocked: bool) -> None:
        await self.state.set_mcp_write_blocked(blocked)
        self._broadcast(
            ConsoleEvent(
                "status",
                connected=self.connected,
                mcp_write_blocked=blocked,
                error=self.error,
            )
        )

    async def write_human(self, data: bytes) -> None:
        await self._write(data, actor="human")

    async def write_mcp(self, data: bytes) -> None:
        await self._write(data, actor="mcp")

    async def _write(self, data: bytes, *, actor: str) -> None:
        if not data or len(data) > self.max_write_bytes:
            raise ValueError("console write size is invalid")
        async with self._write_lock:
            if actor == "mcp" and self.state.mcp_write_blocked:
                raise McpWriteBlocked("MCP console writes are blocked by the operator")
            writer = self._writer
            if writer is None:
                raise ConsoleUnavailable("QEMU console is disconnected")
            writer.write(data)
            await writer.drain()

    async def events(self, queue: asyncio.Queue[ConsoleEvent]) -> AsyncIterator[ConsoleEvent]:
        while True:
            yield await queue.get()
