"""Stable domain errors returned by the MCP service."""

from __future__ import annotations

from typing import Any


class OldSunError(Exception):
    """An expected, safe-to-report failure with a stable machine code."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def invalid_config(message: str, **details: Any) -> OldSunError:
    return OldSunError("CONFIG_INVALID", message, details)

