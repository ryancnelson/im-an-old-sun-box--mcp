from pathlib import Path

import pytest

from old_sun_mcp.config import load_config
from old_sun_mcp.errors import OldSunError


def test_missing_config_is_safe_and_unconfigured(tmp_path: Path) -> None:
    config = load_config(env={}, cwd=tmp_path, home=tmp_path / "home")

    assert config.configured is False
    assert config.run_roots == ()
    assert config.max_output_bytes == 262_144
    assert config.default_timeout_seconds == 30.0


def test_explicit_config_wins_and_parses_adapters_and_recipes(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'''version = 1
default_run = "demo"
max_output_bytes = 1000
default_timeout_seconds = 4
ledger_dir = "ledger"

[[run_roots]]
path = "{run_root}"
manifest = "run.manifest"
console_log = "replay.log"

[paths]
gdb = "/usr/bin/gdb-multiarch"

[debugger_profiles.default]
architecture = "sparc:v9"
endpoint = "127.0.0.1:1234"
timeout_seconds = 12

[guest_adapters.maintenance]
kind = "argv"
socket = "console.sock"
argv = ["runner", "{{socket}}", "{{command}}", "{{timeout}}"]
env_allowlist = ["TERM"]

[trace_recipes.tcg]
argv = ["trace-tcg", "{{pid}}", "{{duration}}"]
max_duration_seconds = 9
requires_privilege = true
''',
        encoding="utf-8",
    )

    config = load_config(
        env={"OLD_SUN_MCP_CONFIG": str(config_path)},
        cwd=tmp_path / "elsewhere",
        home=tmp_path / "home",
    )

    assert config.configured is True
    assert config.source == config_path.resolve()
    assert config.run_roots[0].path == run_root.resolve()
    assert config.default_run == "demo"
    assert config.run_roots[0].console_log == "replay.log"
    assert config.debugger_profiles["default"].architecture == "sparc:v9"
    assert config.debugger_profiles["default"].timeout_seconds == 12
    assert config.guest_adapters["maintenance"].argv[1] == "{socket}"
    assert config.trace_recipes["tcg"].max_duration_seconds == 9
    assert config.ledger_dir == config_path.parent / "ledger"


def test_project_local_config_precedes_xdg_and_home(tmp_path: Path) -> None:
    cwd = tmp_path / "project"
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    cwd.mkdir()
    (xdg / "old-sun-mcp").mkdir(parents=True)
    (home / ".config" / "old-sun-mcp").mkdir(parents=True)
    (cwd / ".old-sun-mcp.toml").write_text("version = 1\n", encoding="utf-8")
    (xdg / "old-sun-mcp" / "config.toml").write_text("version = 1\nmax_output_bytes = 1\n", encoding="utf-8")

    config = load_config(env={"XDG_CONFIG_HOME": str(xdg)}, cwd=cwd, home=home)

    assert config.source == (cwd / ".old-sun-mcp.toml").resolve()
    assert config.max_output_bytes == 262_144


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("version = 1\ncowboy_mode = true\n", encoding="utf-8")

    with pytest.raises(OldSunError) as raised:
        load_config(env={"OLD_SUN_MCP_CONFIG": str(path)}, cwd=tmp_path, home=tmp_path)

    assert raised.value.code == "CONFIG_INVALID"
    assert "cowboy_mode" in raised.value.message


def test_missing_explicit_config_is_typed_error(tmp_path: Path) -> None:
    with pytest.raises(OldSunError) as raised:
        load_config(
            env={"OLD_SUN_MCP_CONFIG": str(tmp_path / "missing.toml")},
            cwd=tmp_path,
            home=tmp_path,
        )

    assert raised.value.code == "CONFIG_NOT_FOUND"


@pytest.mark.parametrize(
    "profile",
    [
        'architecture = "amd64"\n',
        'endpoint = "0.0.0.0:1234"\n',
        'endpoint = "127.0.0.1:70000"\n',
    ],
)
def test_debugger_profile_rejects_non_sparc_or_non_loopback_values(tmp_path: Path, profile: str) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(f"version = 1\n[debugger_profiles.default]\n{profile}", encoding="utf-8")

    with pytest.raises(OldSunError) as raised:
        load_config(env={"OLD_SUN_MCP_CONFIG": str(path)}, cwd=tmp_path, home=tmp_path)

    assert raised.value.code == "CONFIG_INVALID"


def test_qmp_run_root_and_unix_debugger_profile_parse(tmp_path: Path) -> None:
    root = tmp_path / "runs"; root.mkdir()
    path = tmp_path / "qmp.toml"
    path.write_text(
        f'''version = 1
[[run_roots]]
path = "{root}"
manifest = "qemu.argv"
console_log = "logs/console.log"
monitor_kind = "qmp"
monitor_socket = "private/qmp.sock"

[debugger_profiles.default]
architecture = "sparc:v9"
transport = "unix"
endpoint = "private/gdb.sock"
stub = "existing"
''',
        encoding="utf-8",
    )

    config = load_config(env={"OLD_SUN_MCP_CONFIG": str(path)}, cwd=tmp_path, home=tmp_path)

    assert config.run_roots[0].monitor_kind == "qmp"
    assert config.run_roots[0].monitor_socket == "private/qmp.sock"
    assert config.debugger_profiles["default"].transport == "unix"
    assert config.debugger_profiles["default"].stub == "existing"
