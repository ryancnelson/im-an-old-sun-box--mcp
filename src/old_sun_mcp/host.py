"""Exact-process sampling and bounded named host traces."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Callable

from .config import TraceRecipe
from .envelope import truncate_text
from .errors import OldSunError


def _linux_sample(pid: int) -> dict[str, int | str]:
    try:
        fields = open(f"/proc/{pid}/stat", encoding="ascii").read().split()
        status = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in open(f"/proc/{pid}/status", encoding="ascii") if ":" in line}
        io = {line.split(":", 1)[0]: int(line.split(":", 1)[1]) for line in open(f"/proc/{pid}/io", encoding="ascii") if ":" in line}
    except (OSError, ValueError, IndexError) as exc:
        raise OldSunError("PID_NOT_RUNNING", f"Cannot sample PID {pid}: {exc}") from exc
    return {"state": fields[2], "cpu_ticks": int(fields[13]) + int(fields[14]), "rss_bytes": int(status.get("VmRSS", "0 kB").split()[0]) * 1024, "read_bytes": io.get("read_bytes", 0), "write_bytes": io.get("write_bytes", 0)}


def _portable_sample(pid: int) -> dict[str, int | str]:
    if os.path.isdir(f"/proc/{pid}"):
        return _linux_sample(pid)
    result = subprocess.run(["ps", "-p", str(pid), "-o", "state=,rss=,time="], capture_output=True, text=True, timeout=2)
    if result.returncode or not result.stdout.strip():
        raise OldSunError("PID_NOT_RUNNING", f"Cannot sample PID {pid}")
    state, rss, _cpu = result.stdout.split(maxsplit=2)
    return {"state": state, "rss_bytes": int(rss) * 1024}


def process_sample(pid: int, sample_seconds: float = 0.25, *, sampler: Callable[[int], dict[str, Any]] = _portable_sample, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    first = sampler(pid); sleeper(sample_seconds); second = sampler(pid)
    deltas = {key: second[key] - first[key] for key in second.keys() & first.keys() if isinstance(first[key], (int, float)) and isinstance(second[key], (int, float))}
    return {"pid": pid, "sample_seconds": sample_seconds, "first": first, "second": second, "deltas": deltas}


def trace_capabilities() -> dict[str, Any]:
    return {name: {"available": shutil.which(name) is not None, "path": shutil.which(name)} for name in ("bpftrace", "perf", "dtrace", "gdb")}


def run_trace(recipe: TraceRecipe, pid: int, duration_seconds: int, max_bytes: int, *, privileged: bool | None = None) -> dict[str, Any]:
    if duration_seconds < 1 or duration_seconds > recipe.max_duration_seconds:
        raise OldSunError("INVALID_ARGUMENT", "Trace duration is outside recipe bounds", {"maximum": recipe.max_duration_seconds})
    privileged = os.geteuid() == 0 if privileged is None else privileged
    if recipe.requires_privilege and not privileged:
        raise OldSunError("PRIVILEGE_REQUIRED", "Trace recipe requires host privilege")
    argv = [str(pid) if item == "{pid}" else str(duration_seconds) if item == "{duration}" else item for item in recipe.argv]
    started = time.monotonic()
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=duration_seconds + 5, shell=False, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OldSunError("COMMAND_TIMEOUT", "Trace recipe exceeded its cleanup grace period", {"cleanup": "process killed by subprocess timeout"}) from exc
    except OSError as exc:
        raise OldSunError("ADAPTER_UNAVAILABLE", f"Trace recipe could not start: {exc}") from exc
    stdout, out_warning = truncate_text(result.stdout, max_bytes); stderr, err_warning = truncate_text(result.stderr, max_bytes)
    return {"pid": pid, "argv0": argv[0], "duration_seconds": time.monotonic() - started, "exit_status": result.returncode, "stdout": stdout, "stderr": stderr, "cleanup_proved": True, "warnings": [x for x in (out_warning, err_warning) if x]}

