"""Locked append-only evidence and hypothesis events."""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from .errors import OldSunError


SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class Ledger:
    def __init__(self, directory: Path):
        self.directory = directory

    @staticmethod
    def digest(event: dict[str, Any]) -> str:
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(canonical).hexdigest()

    def _path(self, run: str) -> Path:
        if not SAFE_NAME.fullmatch(run):
            raise OldSunError("INVALID_ARGUMENT", "run ledger name contains unsafe characters")
        return self.directory / f"{run}.jsonl"

    def _append(self, run: str, investigation_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not investigation_id.strip():
            raise OldSunError("INVALID_ARGUMENT", "investigation_id is required")
        self.directory.mkdir(parents=True, exist_ok=True)
        event = {"id": f"evt-{uuid.uuid4().hex}", "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "investigation_id": investigation_id, "event_type": event_type, "payload": payload}
        event["digest"] = self.digest(event)
        with self._path(run).open("a", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"); stream.flush(); os_fsync(stream)
            fcntl.flock(stream, fcntl.LOCK_UN)
        return event

    def read(self, run: str, *, investigation_id: str | None = None, after_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        path = self._path(run)
        if not path.exists(): return []
        events = []; seen_after = after_id is None
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try: event = json.loads(line)
            except json.JSONDecodeError as exc: raise OldSunError("COMMAND_FAILED", "Ledger contains a corrupt JSONL record", {"line": number}) from exc
            if not seen_after:
                seen_after = event.get("id") == after_id; continue
            if investigation_id is None or event.get("investigation_id") == investigation_id:
                events.append(event)
            if len(events) >= limit: break
        return events

    def record_evidence(self, run: str, investigation_id: str, layer: str, claim: str, source: str, tool_result_digest: str | None = None, notes: str | None = None) -> dict[str, Any]:
        if not claim.strip() or not source.strip(): raise OldSunError("INVALID_ARGUMENT", "claim and source are required")
        return self._append(run, investigation_id, "evidence", {"layer": layer, "claim": claim, "source": source, "tool_result_digest": tool_result_digest, "notes": notes})

    def start_hypothesis(self, run: str, investigation_id: str, statement: str, predictions: list[str], discriminating_tests: list[str]) -> dict[str, Any]:
        if not statement.strip() or not predictions or not discriminating_tests: raise OldSunError("INVALID_ARGUMENT", "statement, predictions, and discriminating tests are required")
        hypothesis_id = f"hyp-{uuid.uuid4().hex}"
        return self._append(run, investigation_id, "hypothesis_started", {"hypothesis_id": hypothesis_id, "statement": statement, "predictions": predictions, "discriminating_tests": discriminating_tests, "status": "open"})

    def update_hypothesis(self, run: str, investigation_id: str, hypothesis_id: str, status: str, evidence_ids: list[str], reason: str) -> dict[str, Any]:
        if status not in {"open", "supported", "weakened", "falsified", "unresolved"}: raise OldSunError("INVALID_ARGUMENT", "Unknown hypothesis status")
        events = self.read(run, investigation_id=investigation_id)
        if not any(e["event_type"] == "hypothesis_started" and e["payload"]["hypothesis_id"] == hypothesis_id for e in events): raise OldSunError("INVALID_ARGUMENT", "Unknown hypothesis ID")
        known_evidence = {e["id"] for e in events if e["event_type"] == "evidence"}
        if status == "falsified" and not evidence_ids: raise OldSunError("INVALID_ARGUMENT", "Falsified requires evidence")
        if not set(evidence_ids) <= known_evidence: raise OldSunError("INVALID_ARGUMENT", "Unknown evidence ID")
        return self._append(run, investigation_id, "hypothesis_updated", {"hypothesis_id": hypothesis_id, "status": status, "evidence_ids": evidence_ids, "reason": reason})


def os_fsync(stream: Any) -> None:
    import os
    os.fsync(stream.fileno())

