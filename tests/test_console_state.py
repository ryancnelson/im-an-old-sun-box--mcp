import json
import stat

import pytest

from old_sun_mcp.console_state import OperatorState


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
