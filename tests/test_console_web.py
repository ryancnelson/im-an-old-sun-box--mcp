from pathlib import Path
import tempfile

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from old_sun_mcp.console_auth import GitHubIdentity
from old_sun_mcp.console_broker import ConsoleBroker
from old_sun_mcp.console_state import OperatorState
from old_sun_mcp.console_transport import UnixConsoleConnector
from old_sun_mcp.console_web import ConsoleWebConfig, create_console_app


class FakeOAuth:
    def __init__(self, identity: GitHubIdentity):
        self.identity = identity

    def authorize_url(self, state: str) -> str:
        return f"https://github.test/authorize?state={state}"

    async def exchange_identity(self, code: str) -> GitHubIdentity:
        assert code == "code"
        return self.identity


def config(tmp_path: Path, *, development: bool) -> ConsoleWebConfig:
    return ConsoleWebConfig(
        bind_host="127.0.0.1",
        port=8765,
        public_url="http://127.0.0.1:8765" if development else "https://console.unix.wtf",
        state_path=tmp_path / "state.json",
        control_socket=Path("/tmp/unused-control.sock"),
        mcp_token="m" * 32,
        session_secret="s" * 32,
        transport=UnixConsoleConnector(tmp_path / "missing.sock"),
        development_auth=development,
        github_client_id="client",
        github_client_secret="secret",
        github_allowed_login="ryancnelson",
        github_allowed_id=12345,
    )


def test_dev_auth_is_rejected_on_non_loopback() -> None:
    values = {
        "OLD_SUN_CONSOLE_BIND": "0.0.0.0",
        "OLD_SUN_CONSOLE_DEV_AUTH": "1",
        "OLD_SUN_CONSOLE_SOCKET": "/tmp/console.sock",
        "OLD_SUN_CONSOLE_MCP_TOKEN": "m" * 32,
        "OLD_SUN_CONSOLE_SESSION_SECRET": "s" * 32,
    }
    try:
        ConsoleWebConfig.from_env(values)
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback dev auth was accepted")


def test_loopback_dev_login_and_authenticated_state(tmp_path) -> None:
    selected = config(tmp_path, development=True)
    state = OperatorState(selected.state_path)
    state.load()
    broker = ConsoleBroker(selected.transport, state)
    app = create_console_app(selected, broker=broker, manage_services=False)
    with TestClient(app, base_url=selected.public_url) as client:
        assert "GitHub authentication is required" in client.get("/").text
        response = client.get("/login", follow_redirects=True)
        assert "local-dev" in response.text
        assert client.get("/api/state").json()["mcp_write_blocked"] is True
        assert client.get("/static/xterm.js").status_code == 200
        assert response.headers["content-security-policy"].startswith("default-src 'self'")
        app_javascript = client.get("/static/app.js").text
        stylesheet = client.get("/static/ui.css").text
        assert "Liberation Mono" in app_javascript
        assert "Gallant12" not in app_javascript
        assert "Gallant12" not in stylesheet
        with client.websocket_connect(
            "ws://127.0.0.1:8765/ws/console",
            headers={"origin": selected.public_url},
        ) as websocket:
            status = websocket.receive_json()
            assert status["mcp_write_blocked"] is True
            websocket.send_json({"type": "set_mcp_write_blocked", "blocked": False})
            changed = websocket.receive_json()
            assert changed["mcp_write_blocked"] is False


def test_websocket_rejects_missing_session(tmp_path) -> None:
    selected = config(tmp_path, development=True)
    state = OperatorState(selected.state_path)
    state.load()
    broker = ConsoleBroker(selected.transport, state)
    app = create_console_app(selected, broker=broker, manage_services=False)
    with TestClient(app, base_url=selected.public_url) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect("/ws/console", headers={"origin": selected.public_url}):
                pass
        assert caught.value.code == 4403


def test_oauth_callback_denies_wrong_id_and_accepts_pinned_identity(tmp_path) -> None:
    selected = config(tmp_path, development=False)
    state = OperatorState(selected.state_path)
    state.load()
    broker = ConsoleBroker(selected.transport, state)

    denied_app = create_console_app(
        selected,
        broker=broker,
        oauth=FakeOAuth(GitHubIdentity("ryancnelson", 99999)),
        manage_services=False,
    )
    with TestClient(denied_app, base_url=selected.public_url) as client:
        login = client.get("/login", follow_redirects=False)
        oauth_state = login.headers["location"].split("state=", 1)[1]
        denied = client.get(f"/auth/github/callback?state={oauth_state}&code=code")
        assert denied.status_code == 403
        assert denied.json()["error"] == "identity_not_allowed"

    allowed_app = create_console_app(
        selected,
        broker=broker,
        oauth=FakeOAuth(GitHubIdentity("ryancnelson", 12345)),
        manage_services=False,
    )
    with TestClient(allowed_app, base_url=selected.public_url) as client:
        login = client.get("/login", follow_redirects=False)
        oauth_state = login.headers["location"].split("state=", 1)[1]
        allowed = client.get(
            f"/auth/github/callback?state={oauth_state}&code=code",
            follow_redirects=True,
        )
        assert allowed.status_code == 200
        assert "ryancnelson" in allowed.text
