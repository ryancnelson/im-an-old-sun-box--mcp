"""Configured byte-stream transports for local and SSH-accessible consoles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ConsoleEndpoint:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    process: asyncio.subprocess.Process | None = None

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        if self.process is None or self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), 2)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()


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

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(item, str) or not item for item in self.argv):
            raise ValueError("console adapter argv must contain non-empty strings")

    async def connect(self) -> ConsoleEndpoint:
        process = await asyncio.create_subprocess_exec(
            *self.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        if process.stdin is None or process.stdout is None:
            process.kill()
            await process.wait()
            raise RuntimeError("console adapter did not create pipes")
        return ConsoleEndpoint(process.stdout, process.stdin, process)
