"""Evidence-enveloped application service used by MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .config import Config
from .debugger import capture as debugger_capture
from .envelope import failure, success
from .errors import OldSunError
from .guest import console_tail, execute_guest
from .hmp import classify_control, hmp_request, validate_query
from .host import process_sample, run_trace, trace_capabilities
from .ledger import Ledger
from .runs import RunRegistry


class OldSunService:
    def __init__(self, config: Config):
        self.config = config
        self.runs = RunRegistry(config)

    def _call(self, *, layer: str, operation: str, run: str | None, source: dict[str, Any], mutation: str, action: Callable[[], Any]) -> dict[str, Any]:
        try:
            return success(layer=layer, operation=operation, run=run, source=source, mutation=mutation, data=action())
        except OldSunError as exc:
            return failure(layer=layer, operation=operation, run=run, source=source, mutation=mutation, error=exc)
        except Exception:
            return failure(layer=layer, operation=operation, run=run, source=source, mutation=mutation, error=OldSunError("INTERNAL_ERROR", "Unexpected internal failure"))

    @staticmethod
    def _reason(reason: str) -> None:
        if not reason.strip(): raise OldSunError("INVALID_ARGUMENT", "A non-empty reason is required for this operation")

    def lab_list_runs(self, include_stopped: bool = False) -> dict[str, Any]:
        return self._call(layer="lab", operation="lab.list_runs", run=None, source={"kind": "config", "ref": "run_roots"}, mutation="observe", action=lambda: self.runs.list_runs(include_stopped=include_stopped))

    def lab_describe_run(self, run: str) -> dict[str, Any]:
        return self._call(layer="lab", operation="lab.describe_run", run=run, source={"kind": "artifact", "ref": "run.manifest"}, mutation="observe", action=lambda: self.runs.describe(run))

    def lab_classify(self, run: str) -> dict[str, Any]:
        return self._call(layer="lab", operation="lab.classify", run=run, source={"kind": "configured_adapter", "ref": "paths.classifier"}, mutation="observe", action=lambda: (_ for _ in ()).throw(OldSunError("ADAPTER_UNAVAILABLE", "Classifier invocation needs a validated project profile")))

    def guest_console_tail(self, run: str, max_bytes: int | None = None) -> dict[str, Any]:
        return self._call(layer="guest", operation="guest.console_tail", run=run, source={"kind": "file", "ref": "console.log"}, mutation="observe", action=lambda: console_tail(self.runs.resolve(run), min(max_bytes or self.config.max_output_bytes, self.config.max_output_bytes)))

    def guest_exec(self, run: str, command: str, *, reason: str, adapter: str | None = None, timeout_seconds: float | None = None) -> dict[str, Any]:
        def action() -> Any:
            self._reason(reason)
            if not self.config.guest_adapters: raise OldSunError("ADAPTER_UNAVAILABLE", "No guest adapter is configured")
            name = adapter or next(iter(self.config.guest_adapters))
            selected = self.config.guest_adapters.get(name)
            if selected is None: raise OldSunError("ADAPTER_UNAVAILABLE", f"Unknown guest adapter: {name}")
            result = execute_guest(self.runs.resolve(run), selected, command, timeout_seconds or self.config.default_timeout_seconds, self.config.max_output_bytes)
            result["adapter"] = name; result["socket"] = selected.socket
            return result
        return self._call(layer="guest", operation="guest.exec", run=run, source={"kind": "guest_adapter", "ref": adapter or "default"}, mutation="disruptive", action=action)

    def qemu_status(self, run: str) -> dict[str, Any]:
        def action() -> Any:
            resolved = self.runs.resolve(run); identity = self.runs.verify_pid(resolved)
            return {"pid_identity": identity, "monitor": hmp_request(resolved / "monitor.sock", "info status", self.config.default_timeout_seconds, self.config.max_output_bytes)}
        return self._call(layer="emulator", operation="qemu.status", run=run, source={"kind": "unix_socket", "ref": "monitor.sock"}, mutation="observe", action=action)

    def qemu_hmp_query(self, run: str, command: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        def action() -> Any:
            resolved = self.runs.resolve(run); self.runs.verify_pid(resolved); validate_query(command)
            return hmp_request(resolved / "monitor.sock", command, timeout_seconds or self.config.default_timeout_seconds, self.config.max_output_bytes)
        return self._call(layer="emulator", operation="qemu.hmp_query", run=run, source={"kind": "unix_socket", "ref": "monitor.sock"}, mutation="observe", action=action)

    def qemu_hmp_control(self, run: str, command: str, *, reason: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        mutation = "reversible" if command.strip().split(maxsplit=1)[0] in {"stop", "cont"} else "disruptive"
        def action() -> Any:
            self._reason(reason); classified = classify_control(command); resolved = self.runs.resolve(run); self.runs.verify_pid(resolved)
            before = hmp_request(resolved / "monitor.sock", "info status", self.config.default_timeout_seconds, self.config.max_output_bytes)
            response = hmp_request(resolved / "monitor.sock", command, timeout_seconds or self.config.default_timeout_seconds, self.config.max_output_bytes)
            after = hmp_request(resolved / "monitor.sock", "info status", self.config.default_timeout_seconds, self.config.max_output_bytes)
            return {"pre_status": before, "response": response, "post_status": after, "classified_effect": classified}
        return self._call(layer="emulator", operation="qemu.hmp_control", run=run, source={"kind": "unix_socket", "ref": "monitor.sock"}, mutation=mutation, action=action)

    def host_process_sample(self, run: str, sample_seconds: float = 0.25) -> dict[str, Any]:
        return self._call(layer="host", operation="host.process_sample", run=run, source={"kind": "host_process", "ref": "qemu.pid"}, mutation="observe", action=lambda: process_sample(self.runs.verify_pid(self.runs.resolve(run))["pid"], sample_seconds))

    def host_trace_capabilities(self, run: str | None = None) -> dict[str, Any]:
        return self._call(layer="host", operation="host.trace_capabilities", run=run, source={"kind": "host", "ref": "PATH"}, mutation="observe", action=trace_capabilities)

    def host_trace(self, run: str, recipe: str, duration_seconds: int, *, reason: str) -> dict[str, Any]:
        def action() -> Any:
            self._reason(reason); selected = self.config.trace_recipes.get(recipe)
            if selected is None: raise OldSunError("ADAPTER_UNAVAILABLE", f"Unknown trace recipe: {recipe}")
            pid = self.runs.verify_pid(self.runs.resolve(run))["pid"]
            result = run_trace(selected, pid, duration_seconds, self.config.max_output_bytes); result["recipe"] = recipe; return result
        return self._call(layer="host", operation="host.trace", run=run, source={"kind": "trace_recipe", "ref": recipe}, mutation="disruptive", action=action)

    def debugger_capture(self, run: str, *, reason: str, profile: str | None = None) -> dict[str, Any]:
        def action() -> Any:
            self._reason(reason); self.runs.verify_pid(self.runs.resolve(run))
            raise OldSunError("ADAPTER_UNAVAILABLE", "No live debugger profile is validated; cleanup orchestration is available as a library interface")
        return self._call(layer="debugger", operation="debugger.capture", run=run, source={"kind": "debugger_profile", "ref": profile or "default"}, mutation="disruptive", action=action)

    def _ledger(self) -> Ledger:
        if self.config.ledger_dir is None: raise OldSunError("CONFIG_NOT_FOUND", "ledger_dir is not configured")
        return Ledger(self.config.ledger_dir)

    def _ledger_run(self, selector: str) -> str:
        name = self.runs.describe(selector)["name"]
        return name.replace("/", "--")

    def evidence_record(self, run: str, investigation_id: str, layer: str, claim: str, source: str, tool_result_digest: str | None = None, notes: str | None = None) -> dict[str, Any]:
        return self._call(layer="artifact", operation="evidence.record", run=run, source={"kind": "ledger", "ref": "ledger_dir"}, mutation="observe", action=lambda: self._ledger().record_evidence(self._ledger_run(run), investigation_id, layer, claim, source, tool_result_digest, notes))

    def evidence_read(self, run: str, investigation_id: str | None = None, after_id: str | None = None, limit: int = 1000) -> dict[str, Any]:
        return self._call(layer="artifact", operation="evidence.read", run=run, source={"kind": "ledger", "ref": "ledger_dir"}, mutation="observe", action=lambda: self._ledger().read(self._ledger_run(run), investigation_id=investigation_id, after_id=after_id, limit=limit))

    def hypothesis_start(self, run: str, investigation_id: str, statement: str, predictions: list[str], discriminating_tests: list[str]) -> dict[str, Any]:
        return self._call(layer="artifact", operation="hypothesis.start", run=run, source={"kind": "ledger", "ref": "ledger_dir"}, mutation="observe", action=lambda: self._ledger().start_hypothesis(self._ledger_run(run), investigation_id, statement, predictions, discriminating_tests))

    def hypothesis_update(self, run: str, investigation_id: str, hypothesis_id: str, status: str, evidence_ids: list[str], reason: str) -> dict[str, Any]:
        return self._call(layer="artifact", operation="hypothesis.update", run=run, source={"kind": "ledger", "ref": "ledger_dir"}, mutation="observe", action=lambda: self._ledger().update_hypothesis(self._ledger_run(run), investigation_id, hypothesis_id, status, evidence_ids, reason))
