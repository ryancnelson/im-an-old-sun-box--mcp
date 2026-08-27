import os
from pathlib import Path

from old_sun_mcp.config import Config, RunRoot
from old_sun_mcp.service import OldSunService


def test_service_converts_expected_errors_to_envelopes() -> None:
    result = OldSunService(Config()).lab_describe_run("missing")
    assert result["ok"] is False
    assert result["error"]["code"] == "CONFIG_NOT_FOUND"


def test_service_reads_console_with_layer_provenance(tmp_path: Path) -> None:
    root = tmp_path / "runs"; run = root / "demo"; run.mkdir(parents=True)
    (run / "run.manifest").write_text("{}")
    (run / "console.log").write_text("booted")
    config = Config(configured=True, run_roots=(RunRoot(root),), max_output_bytes=100)
    result = OldSunService(config).guest_console_tail("demo")
    assert result["ok"] is True
    assert result["layer"] == "guest"
    assert result["source"]["ref"] == "configured console log"


def test_service_reads_configured_console_name(tmp_path: Path) -> None:
    root = tmp_path / "runs"; run = root / "demo"; run.mkdir(parents=True)
    (run / "manifest.env").write_text("STATUS=PASS\n")
    (run / "replay.log").write_text("niagara boot")
    config = Config(
        configured=True,
        run_roots=(RunRoot(root, manifest="manifest.env", console_log="replay.log"),),
        max_output_bytes=100,
    )

    result = OldSunService(config).guest_console_tail("demo")

    assert result["ok"] is True
    assert result["data"]["text"] == "niagara boot"
    assert result["data"]["ref"] == "replay.log"


def test_guest_exec_requires_reason() -> None:
    result = OldSunService(Config()).guest_exec("demo", "date", reason="")
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_hmp_stop_is_declared_reversible_before_execution() -> None:
    result = OldSunService(Config()).qemu_hmp_control("demo", "stop", reason="inspect")
    assert result["mutation"] == "reversible"
