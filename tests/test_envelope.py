from datetime import datetime

from old_sun_mcp.envelope import failure, success, truncate_text
from old_sun_mcp.errors import OldSunError


def test_success_envelope_has_utc_timestamp_and_required_shape() -> None:
    result = success(
        layer="guest",
        operation="guest.console_tail",
        run="demo",
        source={"kind": "file", "ref": "console.log"},
        mutation="observe",
        data={"text": "booted"},
    )

    assert result["schema_version"] == 1
    assert result["ok"] is True
    assert result["error"] is None
    assert result["warnings"] == []
    assert result["observed_at"].endswith("Z")
    assert datetime.fromisoformat(result["observed_at"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0


def test_failure_envelope_exposes_stable_error_without_traceback() -> None:
    error = OldSunError("RUN_NOT_FOUND", "No such run", {"selector": "nope"})

    result = failure(
        layer="lab",
        operation="lab.describe_run",
        run="nope",
        source={"kind": "config", "ref": "run_roots"},
        mutation="observe",
        error=error,
    )

    assert result["ok"] is False
    assert result["error"] == {
        "code": "RUN_NOT_FOUND",
        "message": "No such run",
        "details": {"selector": "nope"},
    }
    assert "Traceback" not in str(result)


def test_truncate_text_is_utf8_safe_and_reports_byte_counts() -> None:
    text, warning = truncate_text("a☀bc", 5)

    assert text == "a☀b"
    assert warning == {
        "code": "OUTPUT_TRUNCATED",
        "original_bytes": 6,
        "returned_bytes": 5,
    }

