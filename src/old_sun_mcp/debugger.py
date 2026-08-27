"""Debugger orchestration whose cleanup claims are verified."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from .errors import OldSunError


class Monitor(Protocol):
    def status(self) -> str: ...
    def control(self, command: str) -> str: ...


def capture(monitor: Monitor, debugger_runner: Callable[[], dict[str, Any]], *, endpoint: str = "tcp::1234") -> dict[str, Any]:
    pre_status = monitor.status()
    debugger_result: dict[str, Any] | None = None
    debugger_error: Exception | None = None
    monitor.control(f"gdbserver {endpoint}")
    try:
        debugger_result = debugger_runner()
    except Exception as exc:
        debugger_error = exc
    finally:
        try:
            if pre_status == "running": monitor.control("cont")
            post_status = monitor.status()
        except Exception as exc:
            raise OldSunError("CLEANUP_UNPROVED", f"Could not prove debugger cleanup: {exc}") from exc
    if pre_status == "running" and post_status != "running":
        raise OldSunError("CLEANUP_UNPROVED", "QEMU did not return to its pre-debug running state", {"pre_status": pre_status, "post_status": post_status})
    if debugger_error is not None:
        raise OldSunError("COMMAND_FAILED", f"Debugger capture failed: {debugger_error}", {"cleanup_proved": True}) from debugger_error
    return {"pre_status": pre_status, "post_status": post_status, "capture": debugger_result, "cleanup_proved": True}
