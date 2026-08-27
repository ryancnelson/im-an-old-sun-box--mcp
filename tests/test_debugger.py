from pathlib import Path
import subprocess

import pytest

from old_sun_mcp.config import DebuggerProfile
from old_sun_mcp.debugger import capture, run_gdb
from old_sun_mcp.errors import OldSunError


class Monitor:
    def __init__(self, post="running"):
        self.calls = []; self.post = post
    def status(self): return "running" if not self.calls else self.post
    def control(self, command): self.calls.append(command); return "ok"


def test_debugger_always_detaches_and_resumes() -> None:
    monitor = Monitor()
    debugger_calls = []
    result = capture(monitor, lambda: debugger_calls.append("run") or {"registers": "ok"})
    assert result["cleanup_proved"] is True
    assert monitor.calls == ["gdbserver tcp:127.0.0.1:1234", "cont"]


def test_debugger_failure_still_runs_cleanup() -> None:
    monitor = Monitor()
    def fail(): raise RuntimeError("gdb died")
    with pytest.raises(OldSunError) as raised: capture(monitor, fail)
    assert raised.value.code == "COMMAND_FAILED"
    assert monitor.calls[-1] == "cont"


def test_cleanup_must_be_proved() -> None:
    monitor = Monitor(post="paused")
    with pytest.raises(OldSunError) as raised: capture(monitor, lambda: {})
    assert raised.value.code == "CLEANUP_UNPROVED"


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), ValueError("malformed output")])
def test_timeout_and_malformed_output_still_cleanup(failure) -> None:
    monitor = Monitor()
    def fail(): raise failure
    with pytest.raises(OldSunError) as raised: capture(monitor, fail)
    assert raised.value.code == "COMMAND_FAILED"
    assert raised.value.details["cleanup_proved"] is True
    assert monitor.calls[-1] == "cont"


def test_paused_guest_is_restored_to_paused() -> None:
    class PausedMonitor:
        def __init__(self): self.calls = []
        def status(self): return "paused"
        def control(self, command): self.calls.append(command); return {"response": "ok"}

    monitor = PausedMonitor()
    result = capture(monitor, lambda: {"registers": "ok"})

    assert result["post_status"] == "paused"
    assert monitor.calls[-1] == "stop"


def test_gdb_runner_uses_fixed_sparc_batch_and_parses_sections() -> None:
    stdout = """connected
__OLD_SUN_REGISTERS__
pc 0x1000
__OLD_SUN_INSTRUCTIONS__
=> 0x1000: nop
__OLD_SUN_BACKTRACE__
#0 0x1000
__OLD_SUN_DONE__
"""
    calls = []
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    result = run_gdb(Path("/usr/bin/gdb-multiarch"), DebuggerProfile(), 4096, runner=runner)

    argv, kwargs = calls[0]
    assert "set architecture sparc:v9" in argv
    assert "set endian big" in argv
    assert "target remote 127.0.0.1:1234" in argv
    assert kwargs["shell"] is False
    assert result["registers"] == "pc 0x1000"
    assert result["instructions"] == "=> 0x1000: nop"
    assert result["process_exited"] is True


def test_gdb_runner_accepts_resolved_unix_socket_target() -> None:
    stdout = """__OLD_SUN_REGISTERS__
pc 0x1000
__OLD_SUN_INSTRUCTIONS__
0x1000: nop
__OLD_SUN_BACKTRACE__
#0 0x1000
__OLD_SUN_DONE__
"""
    calls = []
    profile = DebuggerProfile(transport="unix", endpoint="private/gdb.sock", stub="existing")
    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    result = run_gdb(Path("gdb-multiarch"), profile, 4096, target="/run/private/gdb.sock", runner=runner)

    assert "target remote /run/private/gdb.sock" in calls[0]
    assert result["transport"] == "unix"
    assert result["endpoint"] == "/run/private/gdb.sock"


def test_gdb_runner_rejects_malformed_output() -> None:
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "not a capture", "")

    with pytest.raises(OldSunError) as raised:
        run_gdb(Path("gdb-multiarch"), DebuggerProfile(), 4096, runner=runner)

    assert raised.value.code == "COMMAND_FAILED"
