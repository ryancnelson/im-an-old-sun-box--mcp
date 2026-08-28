import asyncio
from pathlib import Path, PurePosixPath

import pytest

from old_sun_mcp.console_broker import ConsoleBroker
from old_sun_mcp.console_discovery import ConsoleHost, ConsoleTarget, DiscoveryReport
from old_sun_mcp.console_state import OperatorState, SelectedTargetIdentity
from old_sun_mcp.console_targets import ConsoleTargetManager
from old_sun_mcp.console_transport import UnixConsoleConnector


def target(pid: int = 10, started_at: str = "start-one") -> ConsoleTarget:
    return ConsoleTarget.create(
        host_id="lab",
        socket_path=PurePosixPath("/runs/console.sock"),
        pid=pid,
        started_at=started_at,
        command="qemu-system-sparc64 -serial unix:/runs/console.sock",
        qemu_name="oi",
        socket_mtime=100.0,
    )


class FakeDiscovery:
    def __init__(self, current: ConsoleTarget, connector_path: Path):
        self.current = current
        self.connector_path = connector_path
        self.hosts = (
            ConsoleHost("lab", "Lab", "linux", "root@lab", (PurePosixPath("/runs"),)),
        )
        self.active = 0
        self.maximum_active = 0

    async def discover(self) -> DiscoveryReport:
        return DiscoveryReport((self.current,), {})

    async def revalidate(self, selected: ConsoleTarget) -> ConsoleTarget:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if selected.target_id != self.current.target_id:
            raise ValueError("stale console target")
        return self.current

    def connector(self, selected: ConsoleTarget) -> UnixConsoleConnector:
        return UnixConsoleConnector(self.connector_path)


@pytest.mark.asyncio
async def test_target_selection_is_serialized_persisted_and_broadcast(tmp_path) -> None:
    state = OperatorState(tmp_path / "state.json")
    state.load()
    broker = ConsoleBroker(tmp_path / "missing.sock", state)
    discovery = FakeDiscovery(target(), tmp_path / "other.sock")
    manager = ConsoleTargetManager(discovery, broker, state)
    queue = broker.subscribe()
    await manager.discover()

    await asyncio.gather(manager.select(discovery.current.target_id), manager.select(discovery.current.target_id))

    assert discovery.maximum_active == 1
    assert manager.current == discovery.current
    assert state.selected_target == SelectedTargetIdentity("lab", "/runs/console.sock", 10, "start-one")
    target_events = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.kind == "target":
            target_events.append(event.target)
    assert target_events[-1]["pid"] == 10
    assert target_events[-1]["capabilities"] == {"lifecycle": False}


@pytest.mark.asyncio
async def test_selection_rejects_reused_socket_with_changed_identity(tmp_path) -> None:
    state = OperatorState(tmp_path / "state.json")
    state.load()
    broker = ConsoleBroker(tmp_path / "missing.sock", state)
    original = target()
    discovery = FakeDiscovery(original, tmp_path / "other.sock")
    manager = ConsoleTargetManager(discovery, broker, state)
    await manager.discover()
    discovery.current = target(pid=11, started_at="start-two")

    with pytest.raises(ValueError, match="stale"):
        await manager.select(original.target_id)


@pytest.mark.asyncio
async def test_restore_requires_same_process_identity(tmp_path) -> None:
    state = OperatorState(tmp_path / "state.json")
    await state.set_selected_target(SelectedTargetIdentity("lab", "/runs/console.sock", 10, "start-one"))
    broker = ConsoleBroker(tmp_path / "missing.sock", state)
    discovery = FakeDiscovery(target(pid=11, started_at="start-two"), tmp_path / "other.sock")
    manager = ConsoleTargetManager(discovery, broker, state)

    assert await manager.restore() is None
    assert manager.current is None
    assert state.selected_target is None
