import os
from pathlib import Path

from old_sun_mcp.config import Config, ConsoleConfig, RunRoot
from old_sun_mcp.service import OldSunService


class FakeConsoleClient:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, params=None):
        self.calls.append((method, params or {}))
        if method == "status":
            return {"run": "demo", "console_connected": True}
        return {"method": method, **(params or {})}


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


def test_console_service_uses_configured_broker_and_preserves_binary_input() -> None:
    client = FakeConsoleClient()
    config = Config(console=ConsoleConfig(run="demo"))
    service = OldSunService(config, console_client_factory=lambda: client)

    status = service.console_status()
    write = service.console_write("lease", reason="send OBP command", text="help\r")

    assert status["ok"] is True
    assert status["run"] == "demo"
    assert write["mutation"] == "disruptive"
    assert client.calls[1][0] == "write"
    assert client.calls[1][1]["data_base64"] == "aGVscA0="


def test_console_write_requires_exactly_one_payload_and_reason() -> None:
    service = OldSunService(
        Config(console=ConsoleConfig(run="demo")),
        console_client_factory=FakeConsoleClient,
    )

    missing = service.console_write("lease", reason="test")
    both = service.console_write("lease", reason="test", text="x", data_base64="eA==")
    no_reason = service.console_send_key("lease", "ctrl-c", reason="")

    assert missing["error"]["code"] == "INVALID_ARGUMENT"
    assert both["error"]["code"] == "INVALID_ARGUMENT"
    assert no_reason["error"]["code"] == "INVALID_ARGUMENT"
