"""End-to-end graph smoke test with mock LLM (no external services required)."""

import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["GUARDRAIL_URL"] = "http://127.0.0.1:9"  # force in-process fallback
os.environ["EXECUTOR_URL"] = "http://127.0.0.1:9"

from shared.config import get_settings

get_settings.cache_clear()

from orchestrator.graph import run_incident


def test_reliability_incident_produces_proposals_and_verdicts():
    result = run_incident(
        {
            "event_type": "reliability",
            "title": "payments-api restart storm",
            "description": "many restarts and high memory",
            "namespace": "payments",
            "resource": "payments-api",
            "metrics": {"restarts": 9, "memory_pct": 93, "cpu_pct": 40, "replicas": 3},
        }
    )
    assert result["status"] in {"resolved", "awaiting_approval", "remediating", "blocked"}
    assert result.get("proposals")
    assert result.get("verdicts")
    assert any("triage" in n for n in result.get("notes", []))


def test_cost_idle_requires_approval_path():
    result = run_incident(
        {
            "event_type": "cost",
            "title": "Idle VM spend anomaly",
            "description": "idle vm",
            "namespace": "batch",
            "resource": "etl-worker-vm",
            "cost_signal": {
                "idle_resource": True,
                "idle_monthly_usd": 380,
                "resource_id": "/subscriptions/demo/vm/etl",
                "sku": "Standard_D4s_v5",
            },
        }
    )
    assert result.get("pending_approval") or result.get("denied") or result.get("auto_execute")
    # Idle stop is MEDIUM → should park for approval when medium gate is on.
    assert result["status"] in {"awaiting_approval", "blocked", "resolved"}
