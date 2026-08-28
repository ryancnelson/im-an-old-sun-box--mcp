"""Strict TOML configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from .errors import OldSunError, invalid_config


@dataclass(frozen=True)
class RunRoot:
    path: Path
    manifest: str = "run.manifest"
    console_log: str = "console.log"
    monitor_kind: str = "hmp"
    monitor_socket: str = "monitor.sock"


@dataclass(frozen=True)
class GuestAdapter:
    kind: str
    socket: str
    argv: tuple[str, ...] = ()
    env_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class TraceRecipe:
    argv: tuple[str, ...]
    max_duration_seconds: int
    requires_privilege: bool = False


@dataclass(frozen=True)
class PathsConfig:
    classifier: Path | None = None
    gdb: Path | None = None


@dataclass(frozen=True)
class DebuggerProfile:
    architecture: str = "sparc:v9"
    transport: str = "tcp"
    endpoint: str = "127.0.0.1:1234"
    stub: str = "hmp"
    timeout_seconds: float = 15.0


@dataclass(frozen=True)
class ConsoleControlConfig:
    socket: Path
    run: str
    token_env: str = "OLD_SUN_CONSOLE_MCP_TOKEN"
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class Config:
    configured: bool = False
    source: Path | None = None
    version: int = 1
    default_run: str | None = None
    max_output_bytes: int = 262_144
    default_timeout_seconds: float = 30.0
    run_roots: tuple[RunRoot, ...] = ()
    paths: PathsConfig = field(default_factory=PathsConfig)
    guest_adapters: Mapping[str, GuestAdapter] = field(default_factory=dict)
    trace_recipes: Mapping[str, TraceRecipe] = field(default_factory=dict)
    debugger_profiles: Mapping[str, DebuggerProfile] = field(default_factory=dict)
    console_control: ConsoleControlConfig | None = None
    ledger_dir: Path | None = None


TOP_LEVEL_KEYS = {
    "version",
    "default_run",
    "max_output_bytes",
    "default_timeout_seconds",
    "run_roots",
    "paths",
    "guest_adapters",
    "trace_recipes",
    "debugger_profiles",
    "console_control",
    "ledger_dir",
}


def _unknown_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise invalid_config(f"Unknown {context} key(s): {', '.join(unknown)}")


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise invalid_config(f"{name} must be a positive number")
    return float(value)


def _path_from(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _safe_relative(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise invalid_config(f"{name} must be a string")
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts:
        raise invalid_config(f"{name} must be a safe relative path")
    return value


def _find_config(env: Mapping[str, str], cwd: Path, home: Path) -> tuple[Path | None, bool]:
    explicit = env.get("OLD_SUN_MCP_CONFIG")
    if explicit:
        return Path(explicit).expanduser(), True
    candidates = [cwd / ".old-sun-mcp.toml"]
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg:
        candidates.append(Path(xdg).expanduser() / "old-sun-mcp" / "config.toml")
    else:
        candidates.append(home / ".config" / "old-sun-mcp" / "config.toml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate, False
    return None, False


def load_config(
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> Config:
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else cwd
    home = Path.home() if home is None else home
    selected, explicit = _find_config(env, cwd, home)
    if selected is None:
        return Config()
    if not selected.is_file():
        if explicit:
            raise OldSunError("CONFIG_NOT_FOUND", f"Configuration file not found: {selected}")
        return Config()

    source = selected.resolve()
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise invalid_config(f"Could not read configuration: {exc}", path=str(source)) from exc
    _unknown_keys(raw, TOP_LEVEL_KEYS, "top-level")
    if raw.get("version", 1) != 1:
        raise invalid_config("version must be 1")

    base = source.parent
    run_roots: list[RunRoot] = []
    for index, item in enumerate(raw.get("run_roots", [])):
        if not isinstance(item, dict):
            raise invalid_config(f"run_roots[{index}] must be a table")
        _unknown_keys(
            item,
            {"path", "manifest", "console_log", "monitor_kind", "monitor_socket"},
            f"run_roots[{index}]",
        )
        if not isinstance(item.get("path"), str):
            raise invalid_config(f"run_roots[{index}].path must be a string")
        monitor_kind = item.get("monitor_kind", "hmp")
        if monitor_kind not in {"hmp", "qmp"}:
            raise invalid_config(f"run_roots[{index}].monitor_kind must be hmp or qmp")
        run_roots.append(
            RunRoot(
                _path_from(base, item["path"]),
                _safe_relative(item.get("manifest", "run.manifest"), f"run_roots[{index}].manifest"),
                _safe_relative(item.get("console_log", "console.log"), f"run_roots[{index}].console_log"),
                monitor_kind,
                _safe_relative(item.get("monitor_socket", "monitor.sock"), f"run_roots[{index}].monitor_socket"),
            )
        )

    paths_raw = raw.get("paths", {})
    if not isinstance(paths_raw, dict):
        raise invalid_config("paths must be a table")
    _unknown_keys(paths_raw, {"classifier", "gdb"}, "paths")
    paths = PathsConfig(**{key: _path_from(base, value) for key, value in paths_raw.items()})

    adapters: dict[str, GuestAdapter] = {}
    for name, item in raw.get("guest_adapters", {}).items():
        if not isinstance(item, dict):
            raise invalid_config(f"guest_adapters.{name} must be a table")
        _unknown_keys(item, {"kind", "socket", "argv", "env_allowlist"}, f"guest_adapters.{name}")
        kind = item.get("kind")
        if kind not in {"argv", "fresh-unix-shell"}:
            raise invalid_config(f"guest_adapters.{name}.kind is invalid")
        socket_name = item.get("socket")
        if not isinstance(socket_name, str) or Path(socket_name).is_absolute() or ".." in Path(socket_name).parts:
            raise invalid_config(f"guest_adapters.{name}.socket must be a safe relative path")
        argv = tuple(item.get("argv", ()))
        if kind == "argv" and not argv:
            raise invalid_config(f"guest_adapters.{name}.argv is required")
        adapters[name] = GuestAdapter(kind, socket_name, argv, tuple(item.get("env_allowlist", ())))

    recipes: dict[str, TraceRecipe] = {}
    for name, item in raw.get("trace_recipes", {}).items():
        if not isinstance(item, dict):
            raise invalid_config(f"trace_recipes.{name} must be a table")
        _unknown_keys(item, {"argv", "max_duration_seconds", "requires_privilege"}, f"trace_recipes.{name}")
        argv = tuple(item.get("argv", ()))
        if not argv or "{pid}" not in argv or "{duration}" not in argv:
            raise invalid_config(f"trace_recipes.{name}.argv must contain separate {{pid}} and {{duration}} elements")
        maximum = int(_positive_number(item.get("max_duration_seconds"), f"trace_recipes.{name}.max_duration_seconds"))
        recipes[name] = TraceRecipe(argv, maximum, bool(item.get("requires_privilege", False)))

    debugger_profiles: dict[str, DebuggerProfile] = {}
    for name, item in raw.get("debugger_profiles", {}).items():
        if not isinstance(item, dict):
            raise invalid_config(f"debugger_profiles.{name} must be a table")
        _unknown_keys(
            item,
            {"architecture", "transport", "endpoint", "stub", "timeout_seconds"},
            f"debugger_profiles.{name}",
        )
        architecture = item.get("architecture", "sparc:v9")
        if architecture not in {"sparc", "sparc:v9"}:
            raise invalid_config(f"debugger_profiles.{name}.architecture must be sparc or sparc:v9")
        transport = item.get("transport", "tcp")
        if transport not in {"tcp", "unix"}:
            raise invalid_config(f"debugger_profiles.{name}.transport must be tcp or unix")
        endpoint = item.get("endpoint", "127.0.0.1:1234" if transport == "tcp" else "private/gdb.sock")
        if transport == "tcp":
            if not isinstance(endpoint, str) or not re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{0,4}", endpoint):
                raise invalid_config(f"debugger_profiles.{name}.endpoint must be an IPv4 loopback host and port")
            if int(endpoint.rsplit(":", 1)[1]) > 65535:
                raise invalid_config(f"debugger_profiles.{name}.endpoint port is invalid")
        else:
            endpoint = _safe_relative(endpoint, f"debugger_profiles.{name}.endpoint")
        stub = item.get("stub", "hmp")
        if stub not in {"hmp", "existing"}:
            raise invalid_config(f"debugger_profiles.{name}.stub must be hmp or existing")
        if stub == "hmp" and transport != "tcp":
            raise invalid_config(f"debugger_profiles.{name}.stub hmp requires tcp transport")
        debugger_profiles[name] = DebuggerProfile(
            architecture=architecture,
            transport=transport,
            endpoint=endpoint,
            stub=stub,
            timeout_seconds=_positive_number(
                item.get("timeout_seconds", 15),
                f"debugger_profiles.{name}.timeout_seconds",
            ),
        )

    max_output = int(_positive_number(raw.get("max_output_bytes", 262_144), "max_output_bytes"))
    timeout = _positive_number(raw.get("default_timeout_seconds", 30), "default_timeout_seconds")
    ledger = raw.get("ledger_dir")
    console_control_raw = raw.get("console_control")
    console_control = None
    if console_control_raw is not None:
        if not isinstance(console_control_raw, dict):
            raise invalid_config("console_control must be a table")
        _unknown_keys(console_control_raw, {"socket", "run", "token_env", "timeout_seconds"}, "console_control")
        socket_value = console_control_raw.get("socket")
        run_value = console_control_raw.get("run")
        token_env = console_control_raw.get("token_env", "OLD_SUN_CONSOLE_MCP_TOKEN")
        if not isinstance(socket_value, str) or not isinstance(run_value, str) or not run_value.strip():
            raise invalid_config("console_control.socket and console_control.run are required strings")
        if not isinstance(token_env, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", token_env):
            raise invalid_config("console_control.token_env must be an environment variable name")
        console_control = ConsoleControlConfig(
            socket=_path_from(base, socket_value),
            run=run_value,
            token_env=token_env,
            timeout_seconds=_positive_number(
                console_control_raw.get("timeout_seconds", 5),
                "console_control.timeout_seconds",
            ),
        )
    return Config(
        configured=True,
        source=source,
        version=1,
        default_run=raw.get("default_run"),
        max_output_bytes=max_output,
        default_timeout_seconds=timeout,
        run_roots=tuple(run_roots),
        paths=paths,
        guest_adapters=adapters,
        trace_recipes=recipes,
        debugger_profiles=debugger_profiles,
        console_control=console_control,
        ledger_dir=_path_from(base, ledger) if ledger else None,
    )
