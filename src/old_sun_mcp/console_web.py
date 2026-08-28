"""GitHub-authenticated web client for the console broker."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
import secrets
import time
from typing import Any, Protocol
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import httpx

from .console_broker import ConsoleBroker
from .errors import OldSunError


STATIC_ROOT = Path(__file__).with_name("static")
SESSION_COOKIE = "old_sun_session"
OAUTH_STATE_COOKIE = "old_sun_oauth_state"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SessionSigner:
    def __init__(self, secret: str):
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("session secret must contain at least 32 bytes")
        self.secret = secret.encode("utf-8")

    def issue(self, kind: str, payload: dict[str, Any], *, ttl_seconds: int) -> str:
        body = {
            "kind": kind,
            "exp": int(time.time()) + ttl_seconds,
            "nonce": secrets.token_urlsafe(16),
            "payload": payload,
        }
        encoded = _b64encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = _b64encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(self, token: str | None, kind: str) -> dict[str, Any] | None:
        if not token or token.count(".") != 1:
            return None
        encoded, supplied = token.split(".", 1)
        expected = _b64encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if not secrets.compare_digest(supplied, expected):
            return None
        try:
            body = json.loads(_b64decode(encoded))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(body, dict) or body.get("kind") != kind:
            return None
        expires = body.get("exp")
        payload = body.get("payload")
        if isinstance(expires, bool) or not isinstance(expires, int) or expires < int(time.time()):
            return None
        return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class ConsoleWebConfig:
    public_base_url: str
    github_client_id: str
    github_client_secret: str
    allowed_github_id: int
    allowed_github_login: str
    session_secret: str
    secure_cookies: bool = True
    session_ttl_seconds: int = 8 * 60 * 60
    replay_bytes: int = 262_144

    def __post_init__(self) -> None:
        if not self.public_base_url.startswith(("https://", "http://")):
            raise ValueError("public_base_url must be HTTP or HTTPS")
        if self.allowed_github_id <= 0 or not self.allowed_github_login:
            raise ValueError("a GitHub ID and login are required")
        SessionSigner(self.session_secret)


class OAuthClient(Protocol):
    def authorize_url(self, state: str) -> str: ...
    async def authenticate(self, code: str) -> dict[str, Any]: ...


class GitHubOAuthClient:
    def __init__(self, config: ConsoleWebConfig):
        self.config = config
        self.redirect_uri = f"{config.public_base_url.rstrip('/')}/auth/callback"

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.config.github_client_id,
                "redirect_uri": self.redirect_uri,
                "scope": "read:user",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def authenticate(self, code: str) -> dict[str, Any]:
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.config.github_client_id,
                    "client_secret": self.config.github_client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
            )
            token_response.raise_for_status()
            token_value = token_response.json()
            access_token = token_value.get("access_token") if isinstance(token_value, dict) else None
            if not isinstance(access_token, str) or not access_token:
                raise HTTPException(status_code=502, detail="GitHub did not return an access token")
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            user_response.raise_for_status()
            user = user_response.json()
        if not isinstance(user, dict):
            raise HTTPException(status_code=502, detail="GitHub returned an invalid user")
        return user


def create_console_app(
    config: ConsoleWebConfig,
    broker: ConsoleBroker,
    *,
    oauth_client: OAuthClient | None = None,
    lifespan=None,
) -> FastAPI:
    signer = SessionSigner(config.session_secret)
    oauth = oauth_client or GitHubOAuthClient(config)
    app = FastAPI(title="Old Sun Box Console", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws: wss:; img-src 'self'; frame-ancestors 'none'"
        )
        return response

    def user_from_token(token: str | None) -> dict[str, Any] | None:
        user = signer.verify(token, "session")
        if user is None:
            return None
        user_id = user.get("id")
        login = user.get("login")
        if user_id != config.allowed_github_id or not isinstance(login, str):
            return None
        if login.casefold() != config.allowed_github_login.casefold():
            return None
        return {"id": user_id, "login": login}

    def require_user(request: Request) -> dict[str, Any]:
        user = user_from_token(request.cookies.get(SESSION_COOKIE))
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return user

    def require_origin(request: Request) -> None:
        origin = request.headers.get("origin", "").rstrip("/")
        if not secrets.compare_digest(origin, config.public_base_url.rstrip("/")):
            raise HTTPException(status_code=403, detail="Origin rejected")

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        status = broker.status()
        return {"ok": True, "console_connected": status["console_connected"]}

    @app.get("/login")
    async def login() -> RedirectResponse:
        state = signer.issue("oauth-state", {}, ttl_seconds=300)
        response = RedirectResponse(oauth.authorize_url(state), status_code=302)
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            state,
            max_age=300,
            secure=config.secure_cookies,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.get("/auth/callback")
    async def callback(request: Request, code: str, state: str) -> RedirectResponse:
        cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
        if not cookie_state or not secrets.compare_digest(cookie_state, state):
            raise HTTPException(status_code=403, detail="OAuth state rejected")
        if signer.verify(state, "oauth-state") is None:
            raise HTTPException(status_code=403, detail="OAuth state expired")
        try:
            user = await oauth.authenticate(code)
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="GitHub authentication failed") from exc
        user_id = user.get("id")
        login_name = user.get("login")
        if user_id != config.allowed_github_id:
            raise HTTPException(status_code=403, detail="GitHub identity is not allowed")
        if not isinstance(login_name, str) or login_name.casefold() != config.allowed_github_login.casefold():
            raise HTTPException(status_code=403, detail="GitHub login does not match configured identity")
        session = signer.issue(
            "session",
            {"id": user_id, "login": login_name},
            ttl_seconds=config.session_ttl_seconds,
        )
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(OAUTH_STATE_COOKIE)
        response.set_cookie(
            SESSION_COOKIE,
            session,
            max_age=config.session_ttl_seconds,
            secure=config.secure_cookies,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.get("/logout")
    async def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/")
    async def index(request: Request):
        if user_from_token(request.cookies.get(SESSION_COOKIE)) is None:
            return RedirectResponse("/login", status_code=302)
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/api/session")
    async def session(request: Request) -> dict[str, Any]:
        user = require_user(request)
        return {"user": user, "console": broker.status()}

    @app.post("/api/policy")
    async def policy(request: Request) -> JSONResponse:
        user = require_user(request)
        require_origin(request)
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        enabled = body.get("mcp_write_enabled") if isinstance(body, dict) else None
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="mcp_write_enabled must be a boolean")
        try:
            result = await broker.set_mcp_write_enabled(
                enabled, actor_id=user["id"], actor_login=user["login"]
            )
        except OldSunError as exc:
            raise HTTPException(status_code=500, detail=exc.message) from exc
        return JSONResponse(result)

    @app.websocket("/ws/console")
    async def console_socket(websocket: WebSocket) -> None:
        user = user_from_token(websocket.cookies.get(SESSION_COOKIE))
        if user is None:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        status = broker.status()
        after = max(status["base_cursor"], status["cursor"] - config.replay_bytes)
        replay = broker.read(after, config.replay_bytes)
        await websocket.send_json(
            {
                "type": "initial",
                "status": status,
                "data_base64": base64.b64encode(replay["data"]).decode("ascii"),
                "next_cursor": replay["next_cursor"],
                "user": user,
            }
        )
        events = broker.subscribe()

        async def send_events() -> None:
            while True:
                event = await events.get()
                if event.get("type") == "output":
                    await websocket.send_json(
                        {
                            "type": "output",
                            "data_base64": base64.b64encode(event["data"]).decode("ascii"),
                            "start_cursor": event["start_cursor"],
                            "next_cursor": event["next_cursor"],
                        }
                    )
                else:
                    await websocket.send_json(event)

        sender = asyncio.create_task(send_events())
        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict) or message.get("type") != "input":
                    await websocket.send_json({"type": "error", "message": "Unsupported WebSocket message"})
                    continue
                encoded = message.get("data_base64")
                if not isinstance(encoded, str):
                    await websocket.send_json({"type": "error", "message": "data_base64 is required"})
                    continue
                try:
                    data = base64.b64decode(encoded, validate=True)
                    result = await broker.queue_human_input(data)
                except (ValueError, OldSunError) as exc:
                    text = exc.message if isinstance(exc, OldSunError) else "Invalid base64 input"
                    await websocket.send_json({"type": "error", "message": text})
                    continue
                await websocket.send_json({"type": "input-accepted", "bytes": result["queued"]})
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            broker.unsubscribe(events)

    return app
