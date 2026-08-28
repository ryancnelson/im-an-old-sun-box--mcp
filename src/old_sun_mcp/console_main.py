"""Console broker and web-server entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

import uvicorn

from .console_broker import ConsoleBroker, ConsolePolicyStore, ConsoleTranscript
from .console_rpc import ConsoleRpcServer
from .console_web import ConsoleWebConfig, create_console_app


@dataclass(frozen=True)
class ConsoleRuntimeConfig:
    run_dir: Path
    console_socket: Path
    transcript_path: Path
    policy_path: Path
    rpc_socket: Path
    rpc_token: str
    bind_host: str
    bind_port: int
    transcript_capacity_bytes: int
    web: ConsoleWebConfig


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable is not set: {name}")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int, maximum: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def load_runtime_config(env: Mapping[str, str] | None = None) -> ConsoleRuntimeConfig:
    env = os.environ if env is None else env
    run_dir = Path(_required(env, "OLD_SUN_RUN_DIR")).expanduser().resolve(strict=True)
    if not run_dir.is_dir():
        raise ValueError("OLD_SUN_RUN_DIR must resolve to a directory")

    def path(name: str, default: Path) -> Path:
        raw = env.get(name)
        return Path(raw).expanduser().resolve() if raw else default

    console_socket = path("OLD_SUN_CONSOLE_SOCKET", run_dir / "console.sock")
    if console_socket.parent != run_dir:
        raise ValueError("OLD_SUN_CONSOLE_SOCKET must be directly inside OLD_SUN_RUN_DIR")
    state_root = Path(env.get("OLD_SUN_STATE_ROOT", "/tink/vm-state/oi-basecamp")).expanduser().resolve()
    public_base_url = _required(env, "OLD_SUN_PUBLIC_BASE_URL").rstrip("/")
    allow_insecure = env.get("OLD_SUN_ALLOW_INSECURE_COOKIES") == "1"
    if public_base_url.startswith("http://") and not allow_insecure:
        raise ValueError("HTTP public URLs require OLD_SUN_ALLOW_INSECURE_COOKIES=1")

    web = ConsoleWebConfig(
        public_base_url=public_base_url,
        github_client_id=_required(env, "OLD_SUN_GITHUB_CLIENT_ID"),
        github_client_secret=_required(env, "OLD_SUN_GITHUB_CLIENT_SECRET"),
        allowed_github_id=_positive_int(env, "OLD_SUN_ALLOWED_GITHUB_ID", 0, 2**63 - 1),
        allowed_github_login=env.get("OLD_SUN_ALLOWED_GITHUB_LOGIN", "ryancnelson"),
        session_secret=_required(env, "OLD_SUN_SESSION_SECRET"),
        secure_cookies=not allow_insecure,
        session_ttl_seconds=_positive_int(env, "OLD_SUN_SESSION_TTL_SECONDS", 28_800, 604_800),
        replay_bytes=_positive_int(env, "OLD_SUN_CONSOLE_REPLAY_BYTES", 262_144, 1_048_576),
    )
    return ConsoleRuntimeConfig(
        run_dir=run_dir,
        console_socket=console_socket,
        transcript_path=path("OLD_SUN_CONSOLE_TRANSCRIPT", run_dir / "broker-console.bin"),
        policy_path=path("OLD_SUN_CONSOLE_POLICY", state_root / "console-policy.json"),
        rpc_socket=path("OLD_SUN_CONSOLE_RPC_SOCKET", state_root / "console-broker.sock"),
        rpc_token=_required(env, "OLD_SUN_CONSOLE_MCP_TOKEN"),
        bind_host=env.get("OLD_SUN_CONSOLE_BIND_HOST", "127.0.0.1"),
        bind_port=_positive_int(env, "OLD_SUN_CONSOLE_BIND_PORT", 8765, 65535),
        transcript_capacity_bytes=_positive_int(
            env, "OLD_SUN_CONSOLE_TRANSCRIPT_BYTES", 1_048_576, 16_777_216
        ),
        web=web,
    )


def create_runtime_app(config: ConsoleRuntimeConfig):
    broker = ConsoleBroker(
        console_socket=config.console_socket,
        transcript=ConsoleTranscript(
            config.transcript_path,
            capacity_bytes=config.transcript_capacity_bytes,
        ),
        policy_store=ConsolePolicyStore(config.policy_path),
        run_id=config.run_dir.name,
    )
    rpc = ConsoleRpcServer(config.rpc_socket, config.rpc_token, broker)

    @asynccontextmanager
    async def lifespan(app):
        await broker.start()
        try:
            await rpc.start()
            yield
        finally:
            await rpc.stop()
            await broker.stop()

    return create_console_app(config.web, broker, lifespan=lifespan)


def main() -> None:
    config = load_runtime_config()
    app = create_runtime_app(config)
    # OAuth callbacks contain a short-lived authorization code in the query
    # string. Keep uvicorn's access logger from recording it.
    uvicorn.run(app, host=config.bind_host, port=config.bind_port, log_level="info", access_log=False)
