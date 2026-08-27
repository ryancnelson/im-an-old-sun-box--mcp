import json
import os
from pathlib import Path

import pytest

from old_sun_mcp.config import Config, RunRoot
from old_sun_mcp.errors import OldSunError
from old_sun_mcp.runs import RunRegistry


def configured(*roots: Path, default: str | None = None) -> Config:
    return Config(
        configured=True,
        default_run=default,
        run_roots=tuple(RunRoot(root.resolve()) for root in roots),
    )


def make_run(root: Path, name: str, *, pid: int | None = None) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "run.manifest").write_text('{"intent": "boot test"}', encoding="utf-8")
    if pid is not None:
        (run / "qemu.pid").write_text(str(pid), encoding="ascii")
    return run


def test_list_runs_reports_artifacts_and_can_include_stopped(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    live = make_run(root, "live", pid=os.getpid())
    make_run(root, "stopped")
    (live / "console.log").write_text("ok", encoding="utf-8")
    registry = RunRegistry(configured(root), command_line_reader=lambda pid: str(live / "monitor.sock"))

    assert [item["name"] for item in registry.list_runs()] == ["live"]
    summaries = registry.list_runs(include_stopped=True)
    assert [item["name"] for item in summaries] == ["live", "stopped"]
    assert summaries[0]["artifacts"]["console.log"]["available"] is True


def test_relative_name_must_be_unambiguous(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    make_run(first, "demo")
    make_run(second, "demo")
    registry = RunRegistry(configured(first, second))

    with pytest.raises(OldSunError) as raised:
        registry.resolve("demo")

    assert raised.value.code == "RUN_AMBIGUOUS"


def test_absolute_path_and_symlink_must_stay_inside_root(tmp_path: Path) -> None:
    root, outside = tmp_path / "runs", tmp_path / "outside"
    root.mkdir()
    make_run(outside, "escaped")
    (root / "escape").symlink_to(outside / "escaped", target_is_directory=True)
    registry = RunRegistry(configured(root))

    with pytest.raises(OldSunError) as absolute:
        registry.resolve(str(outside / "escaped"))
    assert absolute.value.code == "RUN_OUTSIDE_ROOT"

    with pytest.raises(OldSunError) as symlink:
        registry.resolve("escape")
    assert symlink.value.code == "RUN_OUTSIDE_ROOT"


@pytest.mark.parametrize("pid_text", ["", "nope", "0", "-2", "1 2"])
def test_malformed_pid_is_rejected(tmp_path: Path, pid_text: str) -> None:
    root = tmp_path / "runs"
    run = make_run(root, "demo")
    (run / "qemu.pid").write_text(pid_text, encoding="ascii")
    registry = RunRegistry(configured(root))

    with pytest.raises(OldSunError) as raised:
        registry.verify_pid(registry.resolve("demo"))

    assert raised.value.code == "PID_INVALID"


def test_pid_identity_requires_command_line_reference_to_run(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run = make_run(root, "demo", pid=os.getpid())
    registry = RunRegistry(configured(root), command_line_reader=lambda pid: "qemu-system-sparc64 -M niagara")

    with pytest.raises(OldSunError) as raised:
        registry.verify_pid(registry.resolve("demo"))

    assert raised.value.code == "PID_IDENTITY_UNPROVED"

    proved = RunRegistry(
        configured(root),
        command_line_reader=lambda pid: f"qemu-system-sparc64 -monitor unix:{run / 'monitor.sock'}",
    ).verify_pid(RunRegistry(configured(root)).resolve("demo"))
    assert proved["pid"] == os.getpid()
    assert proved["identity_proved"] is True


def test_describe_redacts_secret_manifest_keys(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run = make_run(root, "demo", pid=os.getpid())
    (run / "run.manifest").write_text(
        json.dumps({"intent": "debug", "api_token": "nope", "nested": {"password": "also-nope"}}),
        encoding="utf-8",
    )
    registry = RunRegistry(configured(root), command_line_reader=lambda pid: str(run))

    description = registry.describe("demo")

    assert description["manifest"]["intent"] == "debug"
    assert description["manifest"]["api_token"] == "[REDACTED]"
    assert description["manifest"]["nested"]["password"] == "[REDACTED]"
    assert description["pid_verification"]["identity_proved"] is True
