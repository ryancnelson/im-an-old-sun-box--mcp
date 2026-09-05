"""Configured byte-stream transports for local and SSH-accessible consoles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ConsoleEndpoint:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    process: asyncio.subprocess.Process | None = None
    stderr_tail: bytearray = field(default_factory=bytearray)
    stderr_task: asyncio.Task | None = None

    def error_detail(self) -> str:
        text = self.stderr_tail.decode("utf-8", "replace")[-1024:]
        return " ".join("".join(c for c in text if c.isprintable() or c.isspace()).split())

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        if self.process is not None and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.stderr_task is not None:
            self.stderr_task.cancel()
            try:
                await self.stderr_task
            except asyncio.CancelledError:
                pass


class ConsoleConnector(Protocol):
    async def connect(self) -> ConsoleEndpoint: ...


@dataclass(frozen=True)
class UnixConsoleConnector:
    path: Path

    async def connect(self) -> ConsoleEndpoint:
        reader, writer = await asyncio.open_unix_connection(str(self.path))
        return ConsoleEndpoint(reader, writer)


@dataclass(frozen=True)
class ArgvConsoleConnector:
    """Run a fixed adapter whose stdin/stdout are the console byte stream."""

    argv: tuple[str, ...]
    ready_marker: bytes | None = None
    connect_timeout_seconds: float = 10

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(item, str) or not item for item in self.argv):
            raise ValueError("console adapter argv must contain non-empty strings")

    async def connect(self) -> ConsoleEndpoint:
        process = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdin is None or process.stdout is None:
            process.kill()
            await process.wait()
            raise RuntimeError("console adapter did not create pipes")
        endpoint = ConsoleEndpoint(process.stdout, process.stdin, process)
        ready = asyncio.Event()
        marker_seen = False

        async def drain_errors():
            nonlocal marker_seen
            while data := await process.stderr.read(4096):
                endpoint.stderr_tail.extend(data)
                del endpoint.stderr_tail[:-4096]
                if self.ready_marker and self.ready_marker in endpoint.stderr_tail:
                    marker_seen = True
                    ready.set()
            ready.set()

        endpoint.stderr_task = asyncio.create_task(drain_errors())
        try:
            if self.ready_marker is not None:
                await asyncio.wait_for(ready.wait(), self.connect_timeout_seconds)
                if not marker_seen:
                    raise ConnectionError(endpoint.error_detail() or "Console adapter exited before connecting")
            return endpoint
        except BaseException:
            await endpoint.close()
            raise
