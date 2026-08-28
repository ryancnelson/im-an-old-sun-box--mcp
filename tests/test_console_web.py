import base64
from pathlib import Path

from starlette.testclient import TestClient

from old_sun_mcp.console_broker import ConsoleBroker, ConsolePolicyStore, ConsoleTranscript
from old_sun_mcp.console_web import ConsoleWebConfig, SessionSigner, create_console_app


class FakeGitHubOAuth:
    def __init__(self, user):
        self.user = user

    def authorize_url(self, state: str) -> str:
        return f"https://github.test/authorize?state={state}"

    async def authenticate(self, code: str):
        assert code == "good-code"
        return self.user


def config() -> ConsoleWebConfig:
    return ConsoleWebConfig(
        public_base_url="https://console.example.test",
        github_client_id="client",
        github_client_secret="secret",
        allowed_github_id=42,
        allowed_github_login="ryancnelson",
        session_secret="s" * 64,
        secure_cookies=True,
    )


def broker(tmp_path: Path) -> ConsoleBroker:
    transcript = ConsoleTranscript(tmp_path / "transcript.bin")
    transcript.append(b"ok ")
    return ConsoleBroker(
        console_socket=tmp_path / "console.sock",
        transcript=transcript,
        policy_store=ConsolePolicyStore(tmp_path / "policy.json"),
        run_id="demo",
    )


def test_session_signer_rejects_tampering_and_wrong_kind() -> None:
    signer = SessionSigner("s" * 64)
    token = signer.issue("session", {"id": 42, "login": "ryancnelson"}, ttl_seconds=60)

    assert signer.verify(token, "session")["id"] == 42
    assert signer.verify(token, "oauth-state") is None
    assert signer.verify(token + "x", "session") is None


def test_oauth_rejects_matching_login_with_wrong_numeric_id(tmp_path: Path) -> None:
    app = create_console_app(
        config(),
        broker(tmp_path),
        oauth_client=FakeGitHubOAuth({"id": 99, "login": "ryancnelson"}),
    )

    with TestClient(app, base_url="https://console.example.test") as client:
        login = client.get("/login", follow_redirects=False)
        state = login.headers["location"].split("state=", 1)[1]
        denied = client.get(f"/auth/callback?code=good-code&state={state}", follow_redirects=False)

    assert denied.status_code == 403


def test_authorized_user_gets_console_session_and_can_persist_policy(tmp_path: Path) -> None:
    target = broker(tmp_path)
    app = create_console_app(
        config(),
        target,
        oauth_client=FakeGitHubOAuth({"id": 42, "login": "ryancnelson"}),
    )

    with TestClient(app, base_url="https://console.example.test") as client:
        login = client.get("/login", follow_redirects=False)
        state = login.headers["location"].split("state=", 1)[1]
        callback = client.get(f"/auth/callback?code=good-code&state={state}", follow_redirects=False)
        assert callback.status_code == 303

        session = client.get("/api/session")
        assert session.json()["user"] == {"id": 42, "login": "ryancnelson"}
        assert session.json()["console"]["run"] == "demo"

        changed = client.post(
            "/api/policy",
            json={"mcp_write_enabled": False},
            headers={"origin": "https://console.example.test"},
        )
        assert changed.status_code == 200
        assert changed.json()["mcp_write_enabled"] is False
        assert ConsolePolicyStore(tmp_path / "policy.json").load().updated_by_id == 42


def test_authenticated_websocket_receives_replay_and_accepts_human_input(tmp_path: Path) -> None:
    target = broker(tmp_path)
    web_config = config()
    app = create_console_app(web_config, target, oauth_client=FakeGitHubOAuth({"id": 42, "login": "ryancnelson"}))
    session = SessionSigner(web_config.session_secret).issue(
        "session", {"id": 42, "login": "ryancnelson"}, ttl_seconds=60
    )

    with TestClient(app, base_url="https://console.example.test") as client:
        client.cookies.set("old_sun_session", session)
        with client.websocket_connect(
            "/ws/console", headers={"origin": "https://console.example.test"}
        ) as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "initial"
            assert base64.b64decode(initial["data_base64"]) == b"ok "
            websocket.send_json({"type": "input", "data_base64": "Aw=="})
            accepted = websocket.receive_json()
            assert accepted == {"type": "input-accepted", "bytes": 1}

    assert target._input_queue.qsize() == 1
