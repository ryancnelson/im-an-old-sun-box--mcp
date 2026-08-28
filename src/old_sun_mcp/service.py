"""Evidence-enveloped application service used by MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import base64
import binascii
import os

from .config import Config
from .console_client import control_request
from .debugger import HmpMonitor, QmpMonitor, capture as debugger_capture, run_gdb
from .envelope import failure, success
from .errors import OldSunError
from .guest import console_tail, execute_guest
from .hmp import classify_control, hmp_request, validate_query
from .host import process_sample, run_trace, trace_capabilities
from .ledger import Ledger
from .qmp import qmp_request
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
        def action() -> Any:
            resolved = self.runs.resolve(run)
            return console_tail(self.runs.console_log(resolved), min(max_bytes or self.config.max_output_bytes, self.config.max_output_bytes))
        return self._call(layer="guest", operation="guest.console_tail", run=run, source={"kind": "file", "ref": "configured console log"}, mutation="observe", action=action)

    def _console_control(self, run: str | None, operation: str, **values: Any) -> tuple[str, dict[str, Any]]:
        selected = self.config.console_control
        if selected is None:
            raise OldSunError("CONFIG_NOT_FOUND", "console_control is not configured")
        if run is not None and run != selected.run:
            raise OldSunError("RUN_NOT_FOUND", "The console broker is configured for a different run")
        token = os.environ.get(selected.token_env, "")
        if not token:
            raise OldSunError("CONFIG_NOT_FOUND", f"Console token environment variable is absent: {selected.token_env}")
        response = control_request(
            str(selected.socket),
            token,
            {"operation": operation, **values},
            timeout_seconds=selected.timeout_seconds,
            max_bytes=self.config.max_output_bytes,
        )
        return selected.run, response

    def guest_console_status(self, run: str | None = None) -> dict[str, Any]:
        selected_run = run or (self.config.console_control.run if self.config.console_control else None)
        return self._call(
            layer="guest",
            operation="guest.console_status",
            run=selected_run,
            source={"kind": "console_broker", "ref": "configured control socket"},
            mutation="observe",
            action=lambda: self._console_control(run, "status")[1],
        )

    def guest_console_read(self, run: str | None = None, max_bytes: int | None = None) -> dict[str, Any]:
        selected_run = run or (self.config.console_control.run if self.config.console_control else None)
        def action() -> Any:
            _, response = self._console_control(run, "read")
            try:
                data = base64.b64decode(response.pop("data_base64"), validate=True)
            except (KeyError, ValueError, binascii.Error) as exc:
                raise OldSunError("PROTOCOL_ERROR", "Console broker returned invalid history") from exc
            limit = min(max_bytes or self.config.max_output_bytes, self.config.max_output_bytes)
            data = data[-limit:]
            return {
                **response,
                "text": data.decode("utf-8", errors="replace"),
                "data_base64": base64.b64encode(data).decode("ascii"),
                "bytes": len(data),
            }
        return self._call(
            layer="guest",
            operation="guest.console_read",
            run=selected_run,
            source={"kind": "console_broker", "ref": "configured control socket"},
            mutation="observe",
            action=action,
        )

    def guest_console_write(
        self,
        *,
        reason: str,
        run: str | None = None,
        text: str | None = None,
        data_base64: str | None = None,
    ) -> dict[str, Any]:
        selected_run = run or (self.config.console_control.run if self.config.console_control else None)
        def action() -> Any:
            self._reason(reason)
            if (text is None) == (data_base64 is None):
                raise OldSunError("INVALID_ARGUMENT", "Provide exactly one of text or data_base64")
            if text is not None:
                encoded = base64.b64encode(text.encode()).decode("ascii")
            else:
                try:
                    base64.b64decode(data_base64 or "", validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise OldSunError("INVALID_ARGUMENT", "data_base64 is invalid") from exc
                encoded = data_base64 or ""
            return self._console_control(run, "write", reason=reason, data_base64=encoded)[1]
        return self._call(
            layer="guest",
            operation="guest.console_write",
            run=selected_run,
            source={"kind": "console_broker", "ref": "configured control socket"},
            mutation="disruptive",
            action=action,
        )

    def guest_vm_control(self, action: str, *, reason: str, run: str | None = None) -> dict[str, Any]:
        selected_run = run or (self.config.console_control.run if self.config.console_control else None)
        def invoke() -> Any:
            self._reason(reason)
            if action not in {"break", "reset", "powerdown", "start"}:
                raise OldSunError("INVALID_ARGUMENT", "action must be break, reset, powerdown, or start")
            return self._console_control(run, "vm_control", action=action, reason=reason)[1]
        return self._call(
            layer="emulator",
            operation="guest.vm_control",
            run=selected_run,
            source={"kind": "console_broker", "ref": "configured lifecycle adapter"},
            mutation="disruptive",
            action=invoke,
        )

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
            resolved = self.runs.resolve(run)
            identity = self.runs.verify_pid(resolved)
            root = self.runs.run_root(resolved)
            monitor_path = resolved / root.monitor_socket
            if root.monitor_kind == "qmp":
                monitor = {
                    "kind": "qmp",
                    "response": qmp_request(
                        monitor_path,
                        "query-status",
                        self.config.default_timeout_seconds,
                        self.config.max_output_bytes,
                    ),
                }
            else:
                monitor = {
                    "kind": "hmp",
                    **hmp_request(
                        monitor_path,
                        "info status",
                        self.config.default_timeout_seconds,
                        self.config.max_output_bytes,
                    ),
                }
            return {"pid_identity": identity, "monitor": monitor}
        return self._call(layer="emulator", operation="qemu.status", run=run, source={"kind": "unix_socket", "ref": "configured monitor"}, mutation="observe", action=action)

    def qemu_hmp_query(self, run: str, command: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        def action() -> Any:
            resolved = self.runs.resolve(run); self.runs.verify_pid(resolved); validate_query(command)
            root = self.runs.run_root(resolved)
            if root.monitor_kind != "hmp":
                raise OldSunError("ADAPTER_UNAVAILABLE", "This run uses QMP; HMP text queries are unavailable")
            return hmp_request(resolved / root.monitor_socket, command, timeout_seconds or self.config.default_timeout_seconds, self.config.max_output_bytes)
        return self._call(layer="emulator", operation="qemu.hmp_query", run=run, source={"kind": "unix_socket", "ref": "monitor.sock"}, mutation="observe", action=action)

    def qemu_hmp_control(self, run: str, command: str, *, reason: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        mutation = "reversible" if command.strip().split(maxsplit=1)[0] in {"stop", "cont"} else "disruptive"
        def action() -> Any:
            self._reason(reason); classified = classify_control(command); resolved = self.runs.resolve(run); self.runs.verify_pid(resolved)
            root = self.runs.run_root(resolved)
            if root.monitor_kind != "hmp":
                raise OldSunError("ADAPTER_UNAVAILABLE", "This run uses QMP; HMP text controls are unavailable")
            monitor_path = resolved / root.monitor_socket
            before = hmp_request(monitor_path, "info status", self.config.default_timeout_seconds, self.config.max_output_bytes)
            response = hmp_request(monitor_path, command, timeout_seconds or self.config.default_timeout_seconds, self.config.max_output_bytes)
            after = hmp_request(monitor_path, "info status", self.config.default_timeout_seconds, self.config.max_output_bytes)
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
            self._reason(reason)
            resolved = self.runs.resolve(run)
            self.runs.verify_pid(resolved)
            if self.config.paths.gdb is None:
                raise OldSunError("ADAPTER_UNAVAILABLE", "paths.gdb is not configured")
            name = profile or ("default" if "default" in self.config.debugger_profiles else None)
            if name is None and len(self.config.debugger_profiles) == 1:
                name = next(iter(self.config.debugger_profiles))
            selected = self.config.debugger_profiles.get(name or "")
            if selected is None:
                raise OldSunError("ADAPTER_UNAVAILABLE", f"Unknown debugger profile: {name or 'default'}")
            root = self.runs.run_root(resolved)
            monitor_path = resolved / root.monitor_socket
            monitor = (
                QmpMonitor(monitor_path, self.config.default_timeout_seconds, self.config.max_output_bytes)
                if root.monitor_kind == "qmp"
                else HmpMonitor(monitor_path, self.config.default_timeout_seconds, self.config.max_output_bytes)
            )
            target = str(resolved / selected.endpoint) if selected.transport == "unix" else selected.endpoint
            if selected.stub == "hmp" and root.monitor_kind != "hmp":
                raise OldSunError("ADAPTER_UNAVAILABLE", "The debugger profile requires HMP stub setup, but this run uses QMP")
            setup_stub = None
            if selected.stub == "existing":
                setup_stub = lambda: {"mode": "preconfigured", "transport": selected.transport, "endpoint": selected.endpoint}
            result = debugger_capture(
                monitor,
                lambda: run_gdb(self.config.paths.gdb, selected, self.config.max_output_bytes, target=target),
                endpoint=f"tcp:{selected.endpoint}",
                setup_stub=setup_stub,
            )
            result["profile"] = name
            return result
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
