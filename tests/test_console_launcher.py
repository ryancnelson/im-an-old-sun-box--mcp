import json
import stat

import pytest

from old_sun_mcp.console_launcher import credentials


def test_local_launcher_creates_private_persistent_credential_handoff(tmp_path):
    path = tmp_path / "credentials.json"
    first = credentials(path)
    assert len(first["mcp_token"]) >= 32
    assert len(first["session_secret"]) >= 32
    assert first["mcp_token"] != first["session_secret"]
    assert credentials(path) == first
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == first


def test_local_launcher_refuses_shared_credentials(tmp_path):
    path = tmp_path / "credentials.json"
    credentials(path)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        credentials(path)
