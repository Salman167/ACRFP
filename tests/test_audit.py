"""Audit trail smoke tests."""

from pathlib import Path

from shared.audit import AuditStore


def test_audit_append_and_export(tmp_path: Path):
    store = AuditStore(path=tmp_path / "audit.jsonl")
    store.record(
        "incident.ingested",
        "demo incident",
        incident_id="inc_demo",
        actor="test",
        details={"ok": True},
    )
    store.record(
        "guardrail.verdict",
        "allow low risk",
        incident_id="inc_demo",
        actor="guardrail",
    )
    events = store.list(incident_id="inc_demo")
    assert len(events) == 2
    assert "inc_demo" in store.export_json(incident_id="inc_demo")
    csv_text = store.export_csv(incident_id="inc_demo")
    assert "audit_id" in csv_text
    assert "incident.ingested" in csv_text
