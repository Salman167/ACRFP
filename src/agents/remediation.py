"""Remediation agent — MUST emit structured ActionProposal objects only."""

from __future__ import annotations

from agents.llm import chat_json
from shared.models import (
    ActionProposal,
    ActionType,
    CostFinding,
    DiagnosisResult,
    IncidentEvent,
    RiskLevel,
)


def propose_actions(
    event: IncidentEvent,
    diagnosis: DiagnosisResult | None,
    cost: CostFinding | None,
) -> list[ActionProposal]:
    llm_out = chat_json(
        system=(
            "You are a remediation planner. Propose safe structured actions only. "
            "Return JSON: {\"proposals\": [{\"action_type\": ..., \"target\": ..., "
            "\"namespace\": ..., \"parameters\": {}, \"rationale\": ..., "
            "\"expected_impact\": ..., \"reversible\": true, \"risk_hint\": \"low|medium|high|critical\"}]}. "
            f"Allowed action_type values: {[a.value for a in ActionType]}."
        ),
        user={
            "event": event.model_dump(),
            "diagnosis": diagnosis.model_dump() if diagnosis else None,
            "cost": cost.model_dump() if cost else None,
        }.__repr__(),
    )

    proposals: list[ActionProposal] = []
    if isinstance(llm_out, dict) and "proposals" in llm_out:
        for raw in llm_out["proposals"]:
            try:
                proposals.append(ActionProposal.model_validate(raw))
            except Exception:
                continue

    if not proposals:
        proposals = _rule_based_proposals(event, diagnosis, cost)

    region = event.region or "local"
    for p in proposals:
        p.region = region
    return proposals


def _rule_based_proposals(
    event: IncidentEvent,
    diagnosis: DiagnosisResult | None,
    cost: CostFinding | None,
) -> list[ActionProposal]:
    proposals: list[ActionProposal] = []
    ns = event.namespace or "default"
    target = event.resource or "unknown"
    metrics = event.metrics or {}

    hyp = " ".join(diagnosis.root_cause_hypotheses) if diagnosis else ""
    if "restart" in hyp.lower() or int(metrics.get("restarts", 0) or 0) > 3:
        proposals.append(
            ActionProposal(
                action_type=ActionType.RESTART_POD,
                target=target,
                namespace=ns,
                parameters={"grace_period_seconds": 30},
                rationale="Repeated restarts detected; rolling restart to clear bad state",
                expected_impact="Restore healthy replicas without capacity change",
                reversible=True,
                risk_hint=RiskLevel.LOW,
            )
        )

    if float(metrics.get("cpu_pct", 0) or 0) > 90:
        current = int(metrics.get("replicas", 2) or 2)
        proposals.append(
            ActionProposal(
                action_type=ActionType.SCALE_DEPLOYMENT,
                target=target,
                namespace=ns,
                parameters={"replicas": min(current + 2, 10), "current_replicas": current},
                rationale="CPU saturation; scale out within safe bounds",
                expected_impact="Reduce CPU pressure and latency",
                reversible=True,
                risk_hint=RiskLevel.LOW,
            )
        )

    if cost and cost.anomaly_detected and event.cost_signal.get("idle_resource"):
        proposals.append(
            ActionProposal(
                action_type=ActionType.STOP_IDLE_RESOURCE,
                target=str(event.cost_signal.get("resource_id", target)),
                namespace=ns,
                parameters={"sku": event.cost_signal.get("sku"), "dry_run_ok": True},
                rationale="Idle resource driving avoidable spend",
                expected_impact=f"Save ~${cost.estimated_monthly_impact_usd}/month",
                reversible=True,
                risk_hint=RiskLevel.MEDIUM,
            )
        )

    if not proposals:
        proposals.append(
            ActionProposal(
                action_type=ActionType.APPLY_HPA,
                target=target,
                namespace=ns,
                parameters={"min_replicas": 2, "max_replicas": 6, "cpu_target_pct": 70},
                rationale="No specific remediations matched; add HPA as a safe baseline",
                expected_impact="Automatic scale based on CPU",
                reversible=True,
                risk_hint=RiskLevel.LOW,
            )
        )

    return proposals
