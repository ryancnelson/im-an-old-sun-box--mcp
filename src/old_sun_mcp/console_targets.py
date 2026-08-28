"""Serialized global console-target selection."""

from __future__ import annotations

import asyncio
from typing import Any

from .console_broker import ConsoleBroker, McpWriteBlocked
from .console_discovery import ConsoleDiscovery, ConsoleTarget, DiscoveryReport
from .console_state import OperatorState, SelectedTargetIdentity


class ConsoleTargetManager:
    def __init__(self, discovery: ConsoleDiscovery, broker: ConsoleBroker, state: OperatorState):
        self.discovery = discovery
        self.broker = broker
        self.state = state
        self.current: ConsoleTarget | None = None
        self._known: dict[str, ConsoleTarget] = {}
        self._lock = asyncio.Lock()
        self._hosts = {host.host_id: host for host in discovery.hosts}

    async def discover(self) -> DiscoveryReport:
        report = await self.discovery.discover()
        self._known = {target.target_id: target for target in report.targets}
        return report

    @staticmethod
    def _identity(target: ConsoleTarget) -> SelectedTargetIdentity:
        return SelectedTargetIdentity(
            target.host_id,
            str(target.socket_path),
            target.pid,
            target.started_at,
        )

    def _event(self, target: ConsoleTarget) -> dict[str, Any]:
        host = self._hosts[target.host_id]
        return {
            "target_id": target.target_id,
            "host_id": target.host_id,
            "socket_path": str(target.socket_path),
            "pid": target.pid,
            "started_at": target.started_at,
            "qemu_name": target.qemu_name,
            "capabilities": {"lifecycle": host.lifecycle_argv is not None},
        }

    async def select(self, target_id: str, *, actor: str = "human") -> ConsoleTarget:
        async with self._lock:
            if actor == "mcp" and self.state.mcp_write_blocked:
                raise McpWriteBlocked("MCP target changes are blocked by the operator")
            selected = self._known.get(target_id)
            if selected is None:
                raise ValueError("unknown or stale console target; refresh discovery")
            validated = await self.discovery.revalidate(selected)
            await self.broker.replace_transport(self.discovery.connector(validated), clear_history=True)
            await self.state.set_selected_target(self._identity(validated))
            self.current = validated
            self.broker.broadcast_target(self._event(validated))
            return validated

    async def restore(self) -> ConsoleTarget | None:
        saved = self.state.selected_target
        if saved is None:
            return None
        report = await self.discover()
        for candidate in report.targets:
            if self._identity(candidate) == saved:
                return await self.select(candidate.target_id)
        await self.state.set_selected_target(None)
        self.current = None
        return None

    def snapshot(self) -> dict[str, Any] | None:
        return None if self.current is None else self._event(self.current)

    def lifecycle_adapter(self) -> tuple[str, ...] | None:
        if self.current is None:
            return None
        return self._hosts[self.current.host_id].lifecycle_argv
