"""Authenticated xterm.js web console and service entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import html
import ipaddress
import json
import os
from pathlib import Path
import secrets
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .console_auth import GitHubIdentity, GitHubOAuth, identity_allowed
from .console_broker import ConsoleBroker, ConsoleEvent, ConsoleUnavailable
from .console_control import ConsoleControlServer
from .console_discovery import ConsoleHost, parse_hosts_json
from .console_state import OperatorState
from .console_transport import ArgvConsoleConnector, ConsoleConnector, UnixConsoleConnector


@dataclass(frozen=True)
class ConsoleWebConfig:
    bind_host: str
    port: int
    public_url: str
    state_path: Path
    control_socket: Path
    mcp_token: str
    session_secret: str
    transport: ConsoleConnector | None
    hosts: tuple[ConsoleHost, ...] = ()
    lifecycle_adapter: tuple[str, ...] | None = None
    target_label: str = "local host"
    socket_label: str = "configured console"
    transport_label: str = "local"
    development_auth: bool = False
    github_client_id: str = ""
    github_client_secret: str = ""
    github_allowed_login: str = ""
    github_allowed_id: int = 0

    @property
    def callback_url(self) -> str:
        return f"{self.public_url.rstrip('/')}/auth/github/callback"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ConsoleWebConfig":
        values = dict(os.environ if env is None else env)
        bind_host = values.get("OLD_SUN_CONSOLE_BIND", "127.0.0.1")
        try:
            bind_ip = ipaddress.ip_address(bind_host)
        except ValueError as exc:
            raise ValueError("OLD_SUN_CONSOLE_BIND must be an IP address") from exc
        if not bind_ip.is_loopback:
            raise ValueError("console web service must bind to an explicit loopback address")
        development = values.get("OLD_SUN_CONSOLE_DEV_AUTH", "") == "1"

        socket_value = values.get("OLD_SUN_CONSOLE_SOCKET")
        adapter_value = values.get("OLD_SUN_CONSOLE_ADAPTER_JSON")
        hosts_value = values.get("OLD_SUN_CONSOLE_HOSTS_JSON")
        if hosts_value and (socket_value or adapter_value):
            raise ValueError("host registry cannot be combined with a fixed console socket or adapter")
        if not hosts_value and bool(socket_value) == bool(adapter_value):
            raise ValueError("configure exactly one console socket or adapter")

        hosts: tuple[ConsoleHost, ...] = ()
        transport: ConsoleConnector | None = None
        if hosts_value:
            hosts = parse_hosts_json(hosts_value)
        elif socket_value:
            transport = UnixConsoleConnector(Path(socket_value).expanduser().resolve())
        else:
            try:
                raw_argv = json.loads(adapter_value or "")
            except json.JSONDecodeError as exc:
                raise ValueError("OLD_SUN_CONSOLE_ADAPTER_JSON must be a JSON argv array") from exc
            if not isinstance(raw_argv, list) or not all(isinstance(item, str) for item in raw_argv):
                raise ValueError("OLD_SUN_CONSOLE_ADAPTER_JSON must be a JSON argv array")
            transport = ArgvConsoleConnector(tuple(raw_argv))

        lifecycle_value = values.get("OLD_SUN_CONSOLE_LIFECYCLE_ADAPTER_JSON")
        lifecycle_adapter: tuple[str, ...] | None = None
        if lifecycle_value:
            try:
                raw_lifecycle = json.loads(lifecycle_value)
            except json.JSONDecodeError as exc:
                raise ValueError("lifecycle adapter must be a JSON argv array") from exc
            if not isinstance(raw_lifecycle, list) or not raw_lifecycle or not all(
                isinstance(item, str) and item for item in raw_lifecycle
            ):
                raise ValueError("lifecycle adapter must be a non-empty JSON argv array")
            lifecycle_adapter = tuple(raw_lifecycle)

        mcp_token = values.get("OLD_SUN_CONSOLE_MCP_TOKEN", "")
        session_secret = values.get("OLD_SUN_CONSOLE_SESSION_SECRET", "")
        if len(mcp_token) < 32 or len(session_secret) < 32:
            raise ValueError("MCP token and session secret must each be at least 32 characters")

        public_url = values.get("OLD_SUN_CONSOLE_PUBLIC_URL", "http://127.0.0.1:8765")
        parsed = urlparse(public_url)
        if parsed.scheme not in ({"http", "https"} if development else {"https"}) or not parsed.hostname:
            raise ValueError("production public URL must be an absolute HTTPS URL")

        client_id = values.get("OLD_SUN_CONSOLE_GITHUB_CLIENT_ID", "")
        client_secret = values.get("OLD_SUN_CONSOLE_GITHUB_CLIENT_SECRET", "")
        allowed_login = values.get("OLD_SUN_CONSOLE_GITHUB_ALLOWED_LOGIN", "")
        try:
            allowed_id = int(values.get("OLD_SUN_CONSOLE_GITHUB_ALLOWED_ID", "0"))
        except ValueError as exc:
            raise ValueError("GitHub allowed ID must be an integer") from exc
        if not development and (not client_id or not client_secret or not allowed_login or allowed_id <= 0):
            raise ValueError("production GitHub OAuth and immutable identity pin are required")

        return cls(
            bind_host=bind_host,
            port=int(values.get("OLD_SUN_CONSOLE_PORT", "8765")),
            public_url=public_url.rstrip("/"),
            state_path=Path(values.get("OLD_SUN_CONSOLE_STATE", "/var/lib/old-sun-console/state.json")),
            control_socket=Path(values.get("OLD_SUN_CONSOLE_CONTROL_SOCKET", "/var/run/old-sun-console/control.sock")),
            mcp_token=mcp_token,
            session_secret=session_secret,
            transport=transport,
            hosts=hosts,
            lifecycle_adapter=lifecycle_adapter,
            target_label=values.get("OLD_SUN_CONSOLE_TARGET_LABEL", "local host"),
            socket_label=values.get("OLD_SUN_CONSOLE_SOCKET_LABEL", socket_value or "adapter-managed socket"),
            transport_label=values.get("OLD_SUN_CONSOLE_TRANSPORT_LABEL", "local" if socket_value else "adapter"),
            development_auth=development,
            github_client_id=client_id,
            github_client_secret=client_secret,
            github_allowed_login=allowed_login,
            github_allowed_id=allowed_id,
        )


def _authenticated(scope: dict[str, Any]) -> bool:
    session = scope.get("session", {})
    user = session.get("user") if isinstance(session, dict) else None
    return isinstance(user, dict) and isinstance(user.get("id"), int) and isinstance(user.get("login"), str)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self' ws: wss:; img-src 'none'; "
            "script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


def _login_page() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>Old Sun console</title>"
        "<link rel='stylesheet' href='/static/ui.css'></head><body class='login'>"
        "<main><h1>Old Sun console</h1><p>GitHub authentication is required.</p>"
        "<a class='button' href='/login'>Sign in with GitHub</a></main></body></html>"
    )


def _console_page(login: str, config: ConsoleWebConfig) -> HTMLResponse:
    safe_login = html.escape(login)
    target = html.escape(config.target_label)
    socket = html.escape(config.socket_label)
    transport = html.escape(config.transport_label)
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<title>Old Sun console</title><link rel='stylesheet' href='/static/xterm.css'>"
        "<link rel='stylesheet' href='/static/ui.css'></head><body>"
        "<header><div class='header-primary'><strong>console.unix.wtf</strong><span id='connection'>connecting</span>"
        "<nav class='controls'><button data-action='break'>Send Break</button>"
        "<button data-action='reset'>Reset VM</button><button data-action='powerdown'>Power off</button>"
        "<button data-action='start'>Start VM</button></nav>"
        f"<span class='user'>{safe_login}</span><label><input id='mcp-block' type='checkbox' checked> Block MCP typing</label>"
        "<a href='/logout'>Sign out</a></div>"
        f"<div class='connection-detail'>Connected to: <strong>{target}</strong>"
        f"<span class='socket'>{socket}</span><span>via {transport}</span>"
        "<span id='vm-stats'>statistics: waiting</span></div></header><main id='terminal'></main>"
        "<script src='/static/xterm.js'></script><script src='/static/app.js'></script></body></html>"
    )


def create_console_app(
    config: ConsoleWebConfig,
    *,
    broker: ConsoleBroker | None = None,
    oauth: GitHubOAuth | None = None,
    manage_services: bool = True,
) -> Starlette:
    state = OperatorState(config.state_path)
    selected_broker = broker or ConsoleBroker(config.transport, state)
    control = ConsoleControlServer(
        config.control_socket,
        config.mcp_token,
        selected_broker,
        lifecycle_adapter=config.lifecycle_adapter,
    )
    selected_oauth = oauth or GitHubOAuth(
        config.github_client_id,
        config.github_client_secret,
        config.callback_url,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if manage_services:
            await selected_broker.start()
            await control.start()
        app.state.broker = selected_broker
        app.state.control = control
        yield
        if manage_services:
            await control.stop()
            await selected_broker.stop()

    async def home(request: Request) -> Response:
        if not _authenticated(request.scope):
            return _login_page()
        return _console_page(request.session["user"]["login"], config)

    async def login(request: Request) -> Response:
        if config.development_auth:
            request.session["user"] = {"login": "local-dev", "id": -1}
            return RedirectResponse("/", status_code=303)
        state_token = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state_token
        return RedirectResponse(selected_oauth.authorize_url(state_token), status_code=303)

    async def callback(request: Request) -> Response:
        expected = request.session.pop("oauth_state", None)
        supplied = request.query_params.get("state")
        code = request.query_params.get("code")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied) or not code:
            return JSONResponse({"error": "invalid_oauth_callback"}, status_code=403)
        try:
            identity = await selected_oauth.exchange_identity(code)
        except Exception:
            return JSONResponse({"error": "github_oauth_failed"}, status_code=502)
        if not identity_allowed(
            identity,
            login=config.github_allowed_login,
            user_id=config.github_allowed_id,
        ):
            request.session.clear()
            return JSONResponse({"error": "identity_not_allowed"}, status_code=403)
        request.session["user"] = {"login": identity.login, "id": identity.user_id}
        return RedirectResponse("/", status_code=303)

    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def api_state(request: Request) -> Response:
        if not _authenticated(request.scope):
            return JSONResponse({"error": "authentication_required"}, status_code=401)
        return JSONResponse(selected_broker.snapshot())

    async def invoke_lifecycle(action: str) -> tuple[int, dict[str, Any]]:
        if config.lifecycle_adapter is None:
            return 503, {"error": "lifecycle_unavailable"}
        process = await asyncio.create_subprocess_exec(
            *config.lifecycle_adapter,
            action,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        except TimeoutError:
            process.kill()
            await process.wait()
            return 504, {"error": "lifecycle_timeout"}
        result = {
            "action": action,
            "returncode": process.returncode,
            "output": stdout.decode("utf-8", "replace")[-4096:],
            "error_output": stderr.decode("utf-8", "replace")[-4096:],
        }
        return (200 if process.returncode == 0 else 502), result

    async def api_vm_stats(request: Request) -> Response:
        if not _authenticated(request.scope):
            return JSONResponse({"error": "authentication_required"}, status_code=401)
        status, result = await invoke_lifecycle("status")
        if status != 200:
            return JSONResponse(result, status_code=status)
        try:
            payload = json.loads(result["output"].strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return JSONResponse({"error": "invalid_stats_response"}, status_code=502)
        return JSONResponse(payload)

    async def api_lifecycle(request: Request) -> Response:
        if not _authenticated(request.scope):
            return JSONResponse({"error": "authentication_required"}, status_code=401)
        if request.headers.get("origin") != config.public_url:
            return JSONResponse({"error": "origin_rejected"}, status_code=403)
        action = request.path_params["action"]
        if action not in {"break", "reset", "powerdown", "start"}:
            return JSONResponse({"error": "unknown_action"}, status_code=404)
        status, result = await invoke_lifecycle(action)
        return JSONResponse(result, status_code=status)

    async def websocket_console(websocket: WebSocket) -> None:
        expected_origin = config.public_url
        if not _authenticated(websocket.scope) or websocket.headers.get("origin") != expected_origin:
            await websocket.close(code=4403)
            return
        await websocket.accept()
        queue = selected_broker.subscribe()
        await websocket.send_json({"type": "status", **selected_broker.snapshot()})
        history = selected_broker.history.bytes()
        if history:
            await websocket.send_bytes(history)

        async def forward() -> None:
            while True:
                event: ConsoleEvent = await queue.get()
                if event.kind == "output" and event.data is not None:
                    await websocket.send_bytes(event.data)
                elif event.kind == "status":
                    await websocket.send_json(
                        {
                            "type": "status",
                            "connected": event.connected,
                            "mcp_write_blocked": event.mcp_write_blocked,
                        }
                    )

        sender = asyncio.create_task(forward())
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    try:
                        await selected_broker.write_human(message["bytes"])
                    except (ConsoleUnavailable, ValueError) as exc:
                        await websocket.send_json({"type": "input_error", "error": str(exc)})
                elif message.get("text") is not None:
                    try:
                        command = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue
                    if command.get("type") == "set_mcp_write_blocked" and isinstance(command.get("blocked"), bool):
                        await selected_broker.set_mcp_write_blocked(command["blocked"])
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            selected_broker.unsubscribe(queue)

    host = urlparse(config.public_url).hostname or "127.0.0.1"
    middleware = [
        Middleware(TrustedHostMiddleware, allowed_hosts=[host, "127.0.0.1", "localhost", "testserver"]),
        Middleware(SecurityHeadersMiddleware),
        Middleware(
            SessionMiddleware,
            secret_key=config.session_secret,
            https_only=not config.development_auth,
            same_site="lax",
            max_age=8 * 60 * 60,
        ),
    ]
    static_path = Path(__file__).with_name("static")
    return Starlette(
        routes=[
            Route("/", home),
            Route("/login", login),
            Route("/auth/github/callback", callback),
            Route("/logout", logout),
            Route("/healthz", health),
            Route("/api/state", api_state),
            Route("/api/vm-stats", api_vm_stats),
            Route("/api/lifecycle/{action}", api_lifecycle, methods=["POST"]),
            WebSocketRoute("/ws/console", websocket_console),
            Mount("/static", StaticFiles(directory=static_path), name="static"),
        ],
        middleware=middleware,
        lifespan=lifespan,
    )


def main() -> None:
    import uvicorn

    config = ConsoleWebConfig.from_env()
    uvicorn.run(create_console_app(config), host=config.bind_host, port=config.port, proxy_headers=True)
