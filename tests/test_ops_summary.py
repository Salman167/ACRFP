"""Ops summary and incident filters — no LLM, no graph."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.app import APPROVALS, CASES, app
from shared.models import ApprovalRecord, EventType, IncidentCase, IncidentEvent


def _seed() -> None:
    CASES.clear()
    APPROVALS.clear()
    now = datetime.now(timezone.utc)
    CASES["inc_a"] = IncidentCase(
        incident_id="inc_a",
        event=IncidentEvent(
            event_type=EventType.RELIABILITY,
            title="restart storm",
            description="pods restarting",
        ),
        status="resolved",
        created_at=now,
    )
    CASES["inc_b"] = IncidentCase(
        incident_id="inc_b",
        event=IncidentEvent(
            event_type=EventType.COST,
            title="idle vm",
            description="idle spend",
        ),
        status="awaiting_approval",
        created_at=now,
    )
    APPROVALS["apr_1"] = ApprovalRecord(
        approval_id="apr_1",
        proposal_id="prop_1",
        incident_id="inc_b",
        status="pending",
    )


def test_summary_counts_status_and_pending():
    _seed()
    client = TestClient(app)
    res = client.get("/v1/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["incidents_total"] == 2
    assert body["by_status"]["resolved"] == 1
    assert body["by_status"]["awaiting_approval"] == 1
    assert body["by_event_type"]["cost"] == 1
    assert body["pending_approvals"] == 1
    assert body["llm_provider"]
    assert body["policy_pack"]


def test_incidents_filter_by_status():
    _seed()
    client = TestClient(app)
    waiting = client.get("/v1/incidents", params={"status": "awaiting_approval"})
    assert waiting.status_code == 200
    items = waiting.json()
    assert len(items) == 1
    assert items[0]["incident_id"] == "inc_b"

    costs = client.get("/v1/incidents", params={"event_type": "cost"})
    assert [c["incident_id"] for c in costs.json()] == ["inc_b"]
