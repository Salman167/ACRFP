"""
LangGraph state machine for ACRFP.

Flow (defend this diagram in interviews):

  START
    → triage          (decide which specialists to run)
    → diagnosis?      (reliability / mixed)
    → cost?           (cost / mixed)
    → remediate       (structured proposals only)
    → guardrail       (policy proxy — authoritative)
    → split           (allow → executor; require_approval → park; deny → log)
    → END

Specialists never execute. Guardrail never invents actions. Executor never
bypasses guardrail. That separation is the product.
"""

from __future__ import annotations

from typing import Literal

import httpx
from langgraph.graph import END, START, StateGraph

from agents.cost import analyze_cost
from agents.diagnosis import diagnose
from agents.remediation import propose_actions
from orchestrator.state import (
    GraphState,
    cost_from_state,
    diagnosis_from_state,
    event_from_state,
)
from shared.config import get_settings
from shared.models import EventType, GuardrailDecision, new_id


def triage_node(state: GraphState) -> dict:
    event = event_from_state(state)
    plan: list[str] = []
    if event.event_type in {EventType.RELIABILITY, EventType.MIXED}:
        plan.append("diagnosis")
    if event.event_type in {EventType.COST, EventType.MIXED}:
        plan.append("cost")
    if not plan:
        plan = ["diagnosis"]
    return {
        "incident_id": state.get("incident_id") or new_id("inc"),
        "route_plan": plan,
        "status": "triaged",
        "notes": [f"triage: plan={plan}"],
    }


def diagnosis_node(state: GraphState) -> dict:
    result = diagnose(event_from_state(state))
    return {
        "diagnosis": result.model_dump(mode="json"),
        "notes": [f"diagnosis: confidence={result.confidence}"],
    }


def cost_node(state: GraphState) -> dict:
    result = analyze_cost(event_from_state(state))
    return {
        "cost": result.model_dump(mode="json"),
        "notes": [f"cost: anomaly={result.anomaly_detected} impact=${result.estimated_monthly_impact_usd}"],
    }


def remediate_node(state: GraphState) -> dict:
    proposals = propose_actions(
        event_from_state(state),
        diagnosis_from_state(state),
        cost_from_state(state),
    )
    return {
        "proposals": [p.model_dump(mode="json") for p in proposals],
        "notes": [f"remediate: {len(proposals)} proposal(s)"],
    }


def guardrail_node(state: GraphState) -> dict:
    settings = get_settings()
    proposals = state.get("proposals") or []
    verdicts = []

    # Prefer HTTP guardrail service (production shape); fall back to in-process policy.
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{settings.guardrail_url.rstrip('/')}/v1/evaluate/batch",
                json={"proposals": proposals},
            )
            resp.raise_for_status()
            verdicts = resp.json()
    except Exception:
        from guardrail.policy import decide
        from shared.models import ActionProposal

        verdicts = [decide(ActionProposal.model_validate(p)).model_dump(mode="json") for p in proposals]

    auto_execute: list[dict] = []
    pending: list[dict] = []
    denied: list[dict] = []
    by_id = {p["proposal_id"]: p for p in proposals}

    for v in verdicts:
        prop = by_id.get(v["proposal_id"])
        if not prop:
            continue
        decision = v["decision"]
        if decision == GuardrailDecision.ALLOW.value:
            auto_execute.append(prop)
        elif decision == GuardrailDecision.REQUIRE_APPROVAL.value:
            pending.append(prop)
        else:
            denied.append(prop)

    if pending and not auto_execute:
        status = "awaiting_approval"
    elif auto_execute:
        status = "remediating"
    elif denied:
        status = "blocked"
    else:
        status = "resolved"

    return {
        "verdicts": verdicts,
        "auto_execute": auto_execute,
        "pending_approval": pending,
        "denied": denied,
        "status": status,
        "notes": [
            f"guardrail: allow={len(auto_execute)} pending={len(pending)} denied={len(denied)}"
        ],
    }


def executor_node(state: GraphState) -> dict:
    settings = get_settings()
    executions: list[dict] = []
    for prop in state.get("auto_execute") or []:
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"{settings.executor_url.rstrip('/')}/v1/execute",
                    json={"proposal": prop, "dry_run": settings.acrfp_mode == "local"},
                )
                resp.raise_for_status()
                executions.append(resp.json())
        except Exception as exc:
            executions.append(
                {
                    "execution_id": new_id("exec"),
                    "proposal_id": prop.get("proposal_id", "unknown"),
                    "success": False,
                    "dry_run": True,
                    "message": f"executor unreachable: {exc}",
                    "details": {},
                }
            )

    status = state.get("status", "remediating")
    if state.get("pending_approval"):
        status = "awaiting_approval"
    elif executions and all(e.get("success") for e in executions):
        status = "resolved"

    return {
        "executions": executions,
        "status": status,
        "notes": [f"executor: ran={len(executions)}"],
    }


def route_after_triage(state: GraphState) -> Literal["diagnosis", "cost", "remediate"]:
    plan = state.get("route_plan") or []
    if "diagnosis" in plan:
        return "diagnosis"
    if "cost" in plan:
        return "cost"
    return "remediate"


def route_after_diagnosis(state: GraphState) -> Literal["cost", "remediate"]:
    plan = state.get("route_plan") or []
    if "cost" in plan and not state.get("cost"):
        return "cost"
    return "remediate"


def route_after_guardrail(state: GraphState) -> Literal["executor", "__end__"]:
    if state.get("auto_execute"):
        return "executor"
    return "__end__"


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("triage", triage_node)
    g.add_node("diagnosis", diagnosis_node)
    g.add_node("cost", cost_node)
    g.add_node("remediate", remediate_node)
    g.add_node("guardrail", guardrail_node)
    g.add_node("executor", executor_node)

    g.add_edge(START, "triage")
    g.add_conditional_edges(
        "triage",
        route_after_triage,
        {"diagnosis": "diagnosis", "cost": "cost", "remediate": "remediate"},
    )
    g.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {"cost": "cost", "remediate": "remediate"},
    )
    g.add_edge("cost", "remediate")
    g.add_edge("remediate", "guardrail")
    g.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {"executor": "executor", "__end__": END},
    )
    g.add_edge("executor", END)
    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_incident(event_dict: dict) -> GraphState:
    graph = get_graph()
    initial: GraphState = {
        "event": event_dict,
        "notes": [],
        "proposals": [],
        "verdicts": [],
        "auto_execute": [],
        "pending_approval": [],
        "denied": [],
        "executions": [],
        "status": "open",
    }
    return graph.invoke(initial)
