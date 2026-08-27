"""Common evidence envelope and bounded text helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import OldSunError


def observed_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _base(
    *,
    ok: bool,
    layer: str,
    operation: str,
    run: str | None,
    source: dict[str, Any],
    mutation: str,
    data: Any,
    warnings: list[dict[str, Any]] | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": ok,
        "layer": layer,
        "operation": operation,
        "run": run,
        "observed_at": observed_at(),
        "source": source,
        "mutation": mutation,
        "data": data,
        "warnings": warnings or [],
        "error": error,
    }


def success(
    *,
    layer: str,
    operation: str,
    run: str | None,
    source: dict[str, Any],
    mutation: str,
    data: Any,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _base(
        ok=True,
        layer=layer,
        operation=operation,
        run=run,
        source=source,
        mutation=mutation,
        data=data,
        warnings=warnings,
        error=None,
    )


def failure(
    *,
    layer: str,
    operation: str,
    run: str | None,
    source: dict[str, Any],
    mutation: str,
    error: OldSunError,
    data: Any = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _base(
        ok=False,
        layer=layer,
        operation=operation,
        run=run,
        source=source,
        mutation=mutation,
        data=data,
        warnings=warnings,
        error={"code": error.code, "message": error.message, "details": error.details},
    )


def truncate_text(text: str, max_bytes: int) -> tuple[str, dict[str, Any] | None]:
    """Bound text by UTF-8 bytes without returning a partial code point."""
    if max_bytes < 0:
        raise ValueError("max_bytes must not be negative")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, None
    shortened = encoded[:max_bytes].decode("utf-8", errors="ignore")
    returned = len(shortened.encode("utf-8"))
    return shortened, {
        "code": "OUTPUT_TRUNCATED",
        "original_bytes": len(encoded),
        "returned_bytes": returned,
    }

