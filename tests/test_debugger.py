import pytest

from old_sun_mcp.debugger import capture
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
    assert monitor.calls == ["gdbserver tcp::1234", "cont"]


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
