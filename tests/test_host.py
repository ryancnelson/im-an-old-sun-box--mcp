import os
from pathlib import Path

import pytest

from old_sun_mcp.config import TraceRecipe
from old_sun_mcp.errors import OldSunError
from old_sun_mcp.host import process_sample, run_trace


def test_process_sample_returns_deltas() -> None:
    samples = iter([{"cpu_ticks": 10, "read_bytes": 2, "rss_bytes": 100}, {"cpu_ticks": 13, "read_bytes": 7, "rss_bytes": 120}])
    result = process_sample(os.getpid(), 0, sampler=lambda pid: next(samples), sleeper=lambda seconds: None)
    assert result["deltas"] == {"cpu_ticks": 3, "read_bytes": 5, "rss_bytes": 20}


def test_trace_substitutes_pid_and_duration_as_literal_arguments(tmp_path: Path) -> None:
    output = tmp_path / "args"
    script = tmp_path / "trace.py"
    script.write_text("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('|'.join(sys.argv[2:])); print('trace')", encoding="utf-8")
    recipe = TraceRecipe((os.sys.executable, str(script), str(output), "{pid}", "{duration}"), 5)
    result = run_trace(recipe, 123, 2, 1000, privileged=True)
    assert output.read_text() == "123|2"
    assert result["exit_status"] == 0


def test_trace_rejects_duration_and_privilege() -> None:
    recipe = TraceRecipe(("trace", "{pid}", "{duration}"), 2, True)
    with pytest.raises(OldSunError) as duration: run_trace(recipe, 1, 3, 100, privileged=True)
    assert duration.value.code == "INVALID_ARGUMENT"
    with pytest.raises(OldSunError) as privilege: run_trace(recipe, 1, 1, 100, privileged=False)
    assert privilege.value.code == "PRIVILEGE_REQUIRED"

