"""Bounded SPARC GDB capture with verified QEMU state restoration."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Protocol

from .config import DebuggerProfile
from .envelope import truncate_text
from .errors import OldSunError
from .hmp import hmp_request
from .qmp import qmp_request


class Monitor(Protocol):
    def status(self) -> str: ...
    def control(self, command: str) -> Any: ...


class HmpMonitor:
    """Monitor adapter bound to one run's Unix socket."""

    def __init__(self, socket_path: Path, timeout: float, max_bytes: int):
        self.socket_path = socket_path
        self.timeout = timeout
        self.max_bytes = max_bytes

    def _request(self, command: str) -> dict[str, Any]:
        return hmp_request(self.socket_path, command, self.timeout, self.max_bytes)

    def status(self) -> str:
        response = self._request("info status")["response"]
        match = re.search(r"VM status:\s*([^\s]+)", response)
        if match is None:
            raise OldSunError("COMMAND_FAILED", "QEMU returned an unrecognized status response")
        return match.group(1).lower()

    def control(self, command: str) -> dict[str, Any]:
        return self._request(command)


class QmpMonitor:
    """Typed monitor adapter for a run's QMP Unix socket."""

    def __init__(self, socket_path: Path, timeout: float, max_bytes: int):
        self.socket_path = socket_path
        self.timeout = timeout
        self.max_bytes = max_bytes

    def status(self) -> str:
        result = qmp_request(
            self.socket_path,
            "query-status",
            self.timeout,
            self.max_bytes,
        )
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise OldSunError("COMMAND_FAILED", "QMP returned an unrecognized status response")
        return result["status"].lower()

    def control(self, command: str) -> Any:
        if command not in {"stop", "cont"}:
            raise OldSunError("INVALID_ARGUMENT", "Debugger cleanup requested an unsupported QMP command")
        return qmp_request(self.socket_path, command, self.timeout, self.max_bytes)


_MARKERS = (
    "__OLD_SUN_REGISTERS__",
    "__OLD_SUN_INSTRUCTIONS__",
    "__OLD_SUN_BACKTRACE__",
    "__OLD_SUN_DONE__",
)


def _parse_sections(stdout: str) -> dict[str, str]:
    positions = [stdout.find(marker) for marker in _MARKERS]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise OldSunError("COMMAND_FAILED", "GDB returned malformed capture output")
    sections: dict[str, str] = {}
    names = ("registers", "instructions", "backtrace")
    for index, name in enumerate(names):
        start = positions[index] + len(_MARKERS[index])
        sections[name] = stdout[start:positions[index + 1]].strip()
    if not sections["registers"] or not sections["instructions"]:
        raise OldSunError("COMMAND_FAILED", "GDB capture omitted registers or instructions")
    return sections


def run_gdb(
    gdb: Path,
    profile: DebuggerProfile,
    max_bytes: int,
    *,
    target: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    target = target or profile.endpoint
    commands = (
        "set pagination off",
        "set confirm off",
        f"set architecture {profile.architecture}",
        "set endian big",
        f"target remote {target}",
        f"echo \\n{_MARKERS[0]}\\n",
        "info registers",
        f"echo \\n{_MARKERS[1]}\\n",
        "x/16i $pc",
        f"echo \\n{_MARKERS[2]}\\n",
        "bt 32",
        "detach",
        f"echo \\n{_MARKERS[3]}\\n",
    )
    argv = [str(gdb), "-q", "-nx", "-batch"]
    for command in commands:
        argv.extend(("-ex", command))
    started = time.monotonic()
    try:
        result = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=profile.timeout_seconds,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OldSunError("COMMAND_TIMEOUT", "GDB capture exceeded its timeout; the child was killed") from exc
    except OSError as exc:
        raise OldSunError("ADAPTER_UNAVAILABLE", f"GDB could not start: {exc}") from exc
    stdout, stdout_warning = truncate_text(result.stdout, max_bytes)
    stderr, stderr_warning = truncate_text(result.stderr, max_bytes)
    if result.returncode != 0:
        raise OldSunError(
            "COMMAND_FAILED",
            "GDB capture failed",
            {"exit_status": result.returncode, "stdout": stdout, "stderr": stderr},
        )
    sections = _parse_sections(stdout)
    return {
        "argv0": str(gdb),
        "architecture": profile.architecture,
        "endian": "big",
        "endpoint": target,
        "transport": profile.transport,
        "duration_seconds": time.monotonic() - started,
        "exit_status": result.returncode,
        "process_exited": True,
        **sections,
        "stderr": stderr,
        "warnings": [item for item in (stdout_warning, stderr_warning) if item],
    }


def capture(
    monitor: Monitor,
    debugger_runner: Callable[[], dict[str, Any]],
    *,
    endpoint: str = "tcp:127.0.0.1:1234",
    setup_stub: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    pre_status = monitor.status()
    debugger_result: dict[str, Any] | None = None
    debugger_error: Exception | None = None
    stub_setup = monitor.control(f"gdbserver {endpoint}") if setup_stub is None else setup_stub()
    try:
        debugger_result = debugger_runner()
    except Exception as exc:
        debugger_error = exc
    finally:
        try:
            monitor.control("cont" if pre_status == "running" else "stop")
            post_status = monitor.status()
        except Exception as exc:
            raise OldSunError("CLEANUP_UNPROVED", f"Could not prove debugger cleanup: {exc}") from exc
    if post_status != pre_status:
        raise OldSunError(
            "CLEANUP_UNPROVED",
            "QEMU did not return to its pre-debug state",
            {"pre_status": pre_status, "post_status": post_status},
        )
    if debugger_error is not None:
        if isinstance(debugger_error, OldSunError):
            details = dict(debugger_error.details)
            details["cleanup_proved"] = True
            raise OldSunError(debugger_error.code, debugger_error.message, details) from debugger_error
        raise OldSunError(
            "COMMAND_FAILED",
            f"Debugger capture failed: {debugger_error}",
            {"cleanup_proved": True},
        ) from debugger_error
    return {
        "stub_setup": stub_setup,
        "pre_status": pre_status,
        "post_status": post_status,
        "capture": debugger_result,
        "cleanup_proved": True,
    }
