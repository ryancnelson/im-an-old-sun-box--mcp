"""Validated run discovery and exact QEMU process identity."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable

from .config import Config, RunRoot
from .errors import OldSunError


SECRET_KEY = re.compile(r"token|secret|password|credential|authorization|private.?key", re.IGNORECASE)
ARTIFACT_NAMES = ("qemu.pid", "monitor.sock", "console.sock", "console.log", "classifier-state.json")


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _default_command_line(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OldSunError("PID_IDENTITY_UNPROVED", f"Could not read command line for PID {pid}: {exc}") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise OldSunError("PID_IDENTITY_UNPROVED", f"Could not read command line for PID {pid}")
    return result.stdout.strip()


class RunRegistry:
    def __init__(self, config: Config, command_line_reader: Callable[[int], str] | None = None):
        self.config = config
        self.command_line_reader = command_line_reader or _default_command_line

    def _assert_configured(self) -> None:
        if not self.config.configured or not self.config.run_roots:
            raise OldSunError("CONFIG_NOT_FOUND", "No configured run roots")

    def _root_for_canonical(self, canonical: Path) -> RunRoot | None:
        for root in self.config.run_roots:
            if _contained(canonical, root.path.resolve()):
                return root
        return None

    @staticmethod
    def _is_valid(path: Path, root: RunRoot) -> bool:
        return any((path / name).exists() for name in (root.manifest, "qemu.pid"))

    def resolve(self, selector: str | None) -> Path:
        self._assert_configured()
        selector = selector or self.config.default_run
        if not selector:
            raise OldSunError("RUN_NOT_FOUND", "A run selector is required")

        requested = Path(selector).expanduser()
        if requested.is_absolute():
            canonical = requested.resolve()
            root = self._root_for_canonical(canonical)
            if root is None:
                raise OldSunError("RUN_OUTSIDE_ROOT", "Run is outside configured roots", {"selector": selector})
            if not canonical.is_dir() or not self._is_valid(canonical, root):
                raise OldSunError("RUN_INVALID", "Path is not a valid run", {"selector": selector})
            return canonical

        matches: list[Path] = []
        escaped = False
        for root in self.config.run_roots:
            lexical = root.path / requested
            if not lexical.exists():
                continue
            canonical = lexical.resolve()
            if not _contained(canonical, root.path.resolve()):
                escaped = True
                continue
            if canonical.is_dir() and self._is_valid(canonical, root):
                matches.append(canonical)
        unique = list(dict.fromkeys(matches))
        if escaped and not unique:
            raise OldSunError("RUN_OUTSIDE_ROOT", "Run symlink escapes its configured root", {"selector": selector})
        if not unique:
            raise OldSunError("RUN_NOT_FOUND", "Run was not found", {"selector": selector})
        if len(unique) > 1:
            raise OldSunError("RUN_AMBIGUOUS", "Run name exists in more than one root", {"selector": selector})
        return unique[0]

    def _root_for_run(self, run: Path) -> RunRoot:
        root = self._root_for_canonical(run.resolve())
        if root is None:
            raise OldSunError("RUN_OUTSIDE_ROOT", "Resolved run is outside configured roots")
        return root

    @staticmethod
    def _parse_pid(run: Path) -> int:
        path = run / "qemu.pid"
        try:
            text = path.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise OldSunError("PID_INVALID", "Run has no readable qemu.pid", {"path": "qemu.pid"}) from exc
        if not text.isdecimal() or int(text) <= 0:
            raise OldSunError("PID_INVALID", "qemu.pid must contain one positive integer", {"value": text})
        return int(text)

    def verify_pid(self, run: Path) -> dict[str, Any]:
        run = run.resolve()
        self._root_for_run(run)
        pid = self._parse_pid(run)
        try:
            os.kill(pid, 0)
        except ProcessLookupError as exc:
            raise OldSunError("PID_NOT_RUNNING", f"PID {pid} is not running", {"pid": pid}) from exc
        except PermissionError:
            pass
        command_line = self.command_line_reader(pid)
        run_ref = str(run)
        artifact_refs = [str(run / name) for name in ARTIFACT_NAMES]
        if run_ref not in command_line and not any(ref in command_line for ref in artifact_refs):
            raise OldSunError(
                "PID_IDENTITY_UNPROVED",
                "QEMU process identity does not reference this run",
                {"pid": pid},
            )
        return {"pid": pid, "running": True, "identity_proved": True, "command_line": command_line}

    @staticmethod
    def _artifact(path: Path) -> dict[str, Any]:
        available = path.exists()
        result: dict[str, Any] = {"available": available}
        if available:
            stat = path.stat()
            result.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        return result

    def _name(self, run: Path) -> str:
        root = self._root_for_run(run)
        return str(run.relative_to(root.path.resolve()))

    def list_runs(self, *, include_stopped: bool = False) -> list[dict[str, Any]]:
        self._assert_configured()
        found: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for root in self.config.run_roots:
            if not root.path.is_dir():
                continue
            for candidate in sorted(root.path.iterdir(), key=lambda item: item.name):
                if not candidate.is_dir():
                    continue
                canonical = candidate.resolve()
                if canonical in seen or not _contained(canonical, root.path.resolve()) or not self._is_valid(canonical, root):
                    continue
                seen.add(canonical)
                live = False
                pid_status: dict[str, Any]
                try:
                    pid_status = self.verify_pid(canonical)
                    live = True
                except OldSunError as exc:
                    pid_status = {"identity_proved": False, "error": {"code": exc.code, "message": exc.message}}
                if not include_stopped and not live:
                    continue
                manifest = self._read_manifest(canonical)
                found.append(
                    {
                        "name": self._name(canonical),
                        "intent": manifest.get("intent") if isinstance(manifest, dict) else None,
                        "live": live,
                        "pid_verification": pid_status,
                        "artifacts": {name: self._artifact(canonical / name) for name in ARTIFACT_NAMES},
                    }
                )
        return sorted(found, key=lambda item: item["name"])

    def _read_manifest(self, run: Path) -> dict[str, Any]:
        root = self._root_for_run(run)
        path = run / root.manifest
        if not path.is_file():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
            value = json.loads(text)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            result: dict[str, Any] = {}
            for line in text.splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    result[key.strip()] = value.strip()
            return result
        except (OSError, UnicodeError) as exc:
            return {"read_error": str(exc)}

    @classmethod
    def _redact(cls, value: Any, key: str = "") -> Any:
        if SECRET_KEY.search(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {item_key: cls._redact(item_value, str(item_key)) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value

    def describe(self, selector: str | None) -> dict[str, Any]:
        run = self.resolve(selector)
        try:
            pid = self.verify_pid(run)
        except OldSunError as exc:
            pid = {"identity_proved": False, "error": {"code": exc.code, "message": exc.message}}
        return {
            "name": self._name(run),
            "path": str(run),
            "manifest": self._redact(self._read_manifest(run)),
            "pid_verification": pid,
            "capabilities": {
                "hmp": (run / "monitor.sock").exists(),
                "console_log": (run / "console.log").is_file(),
                "console_socket": (run / "console.sock").exists(),
            },
            "artifacts": {name: self._artifact(run / name) for name in ARTIFACT_NAMES},
        }
