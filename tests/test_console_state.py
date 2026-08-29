import json
import stat

import pytest

from old_sun_mcp.console_state import OperatorState, SelectedTargetIdentity


def test_operator_state_defaults_blocked_and_fails_closed(tmp_path) -> None:
    path = tmp_path / "state.json"
    state = OperatorState(path)
    state.load()
    assert state.mcp_write_blocked is True

    path.write_text("broken", encoding="utf-8")
    state.load()
    assert state.mcp_write_blocked is True


@pytest.mark.asyncio
async def test_operator_state_persists_atomically_with_private_mode(tmp_path) -> None:
    path = tmp_path / "state.json"
    state = OperatorState(path)
    await state.set_mcp_write_blocked(False)

    reloaded = OperatorState(path)
    reloaded.load()
    assert reloaded.mcp_write_blocked is False
    assert json.loads(path.read_text()) == {"mcp_write_blocked": False}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".state.json.*")) == []


@pytest.mark.asyncio
async def test_operator_state_persists_selected_target(tmp_path) -> None:
    path = tmp_path / "state.json"
    state = OperatorState(path)
    identity = SelectedTargetIdentity("ec2cicd", "/runs/console.sock", 343827, "start-one")
    await state.set_selected_target(identity)

    reloaded = OperatorState(path)
    reloaded.load()
    assert reloaded.selected_target == identity
    assert json.loads(path.read_text())["selected_target"]["pid"] == 343827
    assert json.loads(path.read_text())["selected_target"]["endpoint"] == "/runs/console.sock"


def test_operator_state_loads_legacy_socket_identity(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        '{"mcp_write_blocked":true,"selected_target":{"host_id":"lab","socket_path":"/runs/console.sock","pid":10,"started_at":"start"}}'
    )
    state = OperatorState(path)
    state.load()
    assert state.selected_target == SelectedTargetIdentity("lab", "/runs/console.sock", 10, "start")


def test_invalid_selected_target_fails_closed(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"mcp_write_blocked":false,"selected_target":{"pid":"oops"}}')
    state = OperatorState(path)
    state.load()
    assert state.mcp_write_blocked is True
    assert state.selected_target is None
