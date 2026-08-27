import json
from pathlib import Path

import pytest

from old_sun_mcp.errors import OldSunError
from old_sun_mcp.ledger import Ledger


def test_ledger_is_append_only_filterable_and_digest_stable(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    first = ledger.record_evidence("run", "inv", "guest", "network is down", "console")
    second = ledger.start_hypothesis("run", "inv", "driver is stuck", ["no interrupts"], ["sample interrupt count"])
    events = ledger.read("run", investigation_id="inv")
    assert [event["id"] for event in events] == [first["id"], second["id"]]
    payload = dict(events[0]); digest = payload.pop("digest")
    assert ledger.digest(payload) == digest


def test_hypothesis_updates_validate_evidence(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    hypothesis = ledger.start_hypothesis("run", "inv", "stuck", ["idle"], ["sample"])
    hypothesis_id = hypothesis["payload"]["hypothesis_id"]
    with pytest.raises(OldSunError): ledger.update_hypothesis("run", "inv", hypothesis_id, "falsified", [], "no")
    evidence = ledger.record_evidence("run", "inv", "host", "QEMU is busy", "sample")
    update = ledger.update_hypothesis("run", "inv", hypothesis_id, "falsified", [evidence["id"]], "busy")
    assert update["payload"]["status"] == "falsified"


def test_corrupt_trailing_line_is_reported(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path); ledger.record_evidence("run", "inv", "guest", "x", "y")
    with (tmp_path / "run.jsonl").open("a") as stream: stream.write("{")
    with pytest.raises(OldSunError) as raised: ledger.read("run")
    assert raised.value.code == "COMMAND_FAILED"
