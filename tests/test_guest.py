import os
from pathlib import Path

import pytest

from old_sun_mcp.config import GuestAdapter
from old_sun_mcp.errors import OldSunError
from old_sun_mcp.guest import console_tail, execute_guest


def test_console_tail_is_bounded_from_end(tmp_path: Path) -> None:
    (tmp_path / "console.log").write_text("0123456789", encoding="utf-8")
    result = console_tail(tmp_path, 4)
    assert result["text"] == "6789"
    assert result["original_bytes"] == 10


def test_argv_adapter_preserves_command_as_one_argument(tmp_path: Path) -> None:
    output = tmp_path / "argv.txt"
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('\\n'.join(sys.argv[2:])); print('ok')",
        encoding="utf-8",
    )
    adapter = GuestAdapter("argv", "guest.sock", (os.sys.executable, str(runner), str(output), "{command}", "{timeout}"))
    result = execute_guest(tmp_path, adapter, "echo hi; touch /nope", 2, 1000)
    assert result["exit_status"] == 0
    assert output.read_text().splitlines()[0] == "echo hi; touch /nope"


def test_guest_timeout_is_typed(tmp_path: Path) -> None:
    adapter = GuestAdapter("argv", "guest.sock", (os.sys.executable, "-c", "import time; time.sleep(5)", "{command}"))
    with pytest.raises(OldSunError) as raised:
        execute_guest(tmp_path, adapter, "date", 0.01, 1000)
    assert raised.value.code == "COMMAND_TIMEOUT"


def test_nonzero_guest_exit_is_evidence_not_transport_failure(tmp_path: Path) -> None:
    adapter = GuestAdapter("argv", "guest.sock", (os.sys.executable, "-c", "raise SystemExit(7)", "{command}"))
    assert execute_guest(tmp_path, adapter, "false", 1, 1000)["exit_status"] == 7


def test_fresh_shell_transport_failure_is_typed(tmp_path: Path) -> None:
    adapter = GuestAdapter("fresh-unix-shell", "missing.sock")
    with pytest.raises(OldSunError) as raised:
        execute_guest(tmp_path, adapter, "date", 1, 1000)
    assert raised.value.code == "SOCKET_CONNECT_FAILED"
