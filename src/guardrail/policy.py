"""
Guardrail policy engine — loads YAML policy packs, then applies deterministic rules.

DESIGN DECISIONS (be ready to defend these in interviews):

1. Agents never call kubectl/ARM directly. Every action is a typed ActionProposal
   that must pass through this policy proxy first.

2. Risk is determined by ACTION TYPE + PARAMETERS, not by the LLM's self-rating.
   The agent's risk_hint is advisory only; policy is authoritative.

3. Default stance is deny-unknown: if we don't recognize an action type, DENY.

4. Destructive / irreversible / blast-radius-high actions always need a human
   (or are denied outright for CRITICAL).

5. Policy packs (local/prod) live in data/policies/*.yaml — tunable without recoding.

6. HIGH risk can require dual approval (two distinct humans).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from shared.config import get_settings
from shared.models import (
    ActionProposal,
    ActionType,
    GuardrailDecision,
    GuardrailVerdict,
    RiskLevel,
)

POLICY_DIR = Path(__file__).resolve().parents[2] / "data" / "policies"


@lru_cache
def load_policy_pack(name: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    pack = (name or settings.policy_pack or "local").lower()
    path = POLICY_DIR / f"{pack}.yaml"
    if not path.exists():
        path = POLICY_DIR / "local.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def reload_policy_pack() -> dict[str, Any]:
    load_policy_pack.cache_clear()
    return load_policy_pack()


def _risk_from_str(value: str) -> RiskLevel:
    return RiskLevel(value.lower())


def base_risk_map(pack: dict[str, Any]) -> dict[ActionType, RiskLevel]:
    raw = pack.get("base_risk") or {}
    out: dict[ActionType, RiskLevel] = {}
    for key, val in raw.items():
        try:
            out[ActionType(key)] = _risk_from_str(str(val))
        except ValueError:
            continue
    return out


def required_approvals_for(risk: RiskLevel, pack: dict[str, Any] | None = None) -> int:
    pack = pack or load_policy_pack()
    decisions = pack.get("decisions") or {}
    if risk == RiskLevel.HIGH and decisions.get("dual_approval_for_high", True):
        return int(decisions.get("high_required_approvals", 2))
    if risk == RiskLevel.MEDIUM:
        return int(decisions.get("medium_required_approvals", 1))
    if risk == RiskLevel.LOW:
        return 1
    return 99  # critical / unknown — should be denied, not approved


def _rank(level: RiskLevel) -> int:
    return {
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
        RiskLevel.CRITICAL: 4,
    }[level]


def _escalate(current: RiskLevel, floor: RiskLevel) -> RiskLevel:
    return current if _rank(current) >= _rank(floor) else floor


def classify_risk(proposal: ActionProposal) -> tuple[RiskLevel, list[str], list[str]]:
    """Return (risk, reasons, policy_ids). Pure-ish — driven by YAML pack."""

    pack = load_policy_pack()
    base = base_risk_map(pack)
    protected = {str(x).lower() for x in (pack.get("protected_namespaces") or [])}
    limits = pack.get("limits") or {}
    max_replicas = int(limits.get("max_auto_scale_replicas", 10))
    max_delta = int(limits.get("max_scale_delta", 5))

    reasons: list[str] = []
    policy_ids: list[str] = []
    policy_ids.append(f"POL-PACK-{pack.get('policy_pack', 'local')}")

    if proposal.action_type not in base:
        return RiskLevel.CRITICAL, ["Unknown action type — deny-unknown policy"], ["POL-UNKNOWN-001"]

    risk = base[proposal.action_type]
    policy_ids.append(f"POL-BASE-{proposal.action_type.value}")
    reasons.append(f"Base risk for {proposal.action_type.value} is {risk.value}")

    ns = (proposal.namespace or "").lower()
    if ns in protected:
        risk = _escalate(risk, RiskLevel.HIGH)
        policy_ids.append("POL-NS-PROTECTED-001")
        reasons.append(f"Namespace '{ns}' is protected; escalated to at least HIGH")

    if proposal.action_type == ActionType.SCALE_DEPLOYMENT:
        replicas = int(proposal.parameters.get("replicas", 0))
        current = proposal.parameters.get("current_replicas")
        if replicas <= 0:
            risk = _escalate(risk, RiskLevel.HIGH)
            policy_ids.append("POL-SCALE-ZERO-001")
            reasons.append("Scaling to 0 is effectively an outage — HIGH")
        elif replicas > max_replicas:
            risk = _escalate(risk, RiskLevel.MEDIUM)
            policy_ids.append("POL-SCALE-CAP-001")
            reasons.append(f"Replica target {replicas} exceeds auto cap {max_replicas}")
        if current is not None:
            delta = abs(int(current) - replicas)
            if int(current) > replicas:
                risk = _escalate(risk, RiskLevel.MEDIUM)
                policy_ids.append("POL-SCALE-DOWN-001")
                reasons.append("Scale-down can drop capacity — MEDIUM minimum")
            if delta > max_delta:
                risk = _escalate(risk, RiskLevel.MEDIUM)
                policy_ids.append("POL-SCALE-DELTA-001")
                reasons.append(f"Replica delta {delta} exceeds {max_delta}")

    if proposal.action_type == ActionType.PATCH_RESOURCES:
        risk = _escalate(risk, RiskLevel.MEDIUM)
        policy_ids.append("POL-RES-PATCH-001")
        reasons.append("Resource patches are capacity-sensitive — MEDIUM minimum")

    if not proposal.reversible and _rank(risk) < _rank(RiskLevel.HIGH):
        risk = _escalate(risk, RiskLevel.HIGH)
        policy_ids.append("POL-IRREVERSIBLE-001")
        reasons.append("Marked irreversible — escalated to HIGH")

    if _rank(proposal.risk_hint) > _rank(risk):
        risk = proposal.risk_hint
        policy_ids.append("POL-HINT-ESCALATE-001")
        reasons.append(f"Agent risk_hint escalated to {proposal.risk_hint.value}")

    return risk, reasons, policy_ids


def decide(proposal: ActionProposal) -> GuardrailVerdict:
    """Map classified risk → allow / require_approval / deny."""

    settings = get_settings()
    pack = load_policy_pack()
    decisions = pack.get("decisions") or {}
    risk, reasons, policy_ids = classify_risk(proposal)

    # Sovereign / region lock — deny actions outside allowed Azure regions.
    allowed = {str(x).lower() for x in (pack.get("allowed_regions") or [])}
    region = (proposal.region or "local").lower()
    if allowed and region not in allowed:
        return GuardrailVerdict(
            decision=GuardrailDecision.DENY,
            risk_level=RiskLevel.CRITICAL,
            reasons=[
                f"Region '{region}' is outside sovereign allow-list {sorted(allowed)}"
            ],
            policy_ids=["POL-REGION-LOCK-001"],
            proposal_id=proposal.proposal_id,
            required_approvals=0,
        )

    auto_low = bool(decisions.get("auto_execute_low_risk", settings.auto_execute_low_risk))
    require_medium = bool(decisions.get("require_human_for_medium", settings.require_human_for_medium))
    deny_critical = bool(decisions.get("deny_critical_by_default", settings.deny_critical_by_default))

    if risk == RiskLevel.CRITICAL and deny_critical:
        decision = GuardrailDecision.DENY
        reasons.append("CRITICAL actions denied by default in this environment")
        policy_ids.append("POL-CRITICAL-DENY-001")
    elif risk == RiskLevel.LOW and auto_low:
        decision = GuardrailDecision.ALLOW
        reasons.append("LOW risk auto-execute enabled")
        policy_ids.append("POL-AUTO-LOW-001")
    elif risk in {RiskLevel.MEDIUM, RiskLevel.HIGH} and require_medium:
        decision = GuardrailDecision.REQUIRE_APPROVAL
        need = required_approvals_for(risk, pack)
        reasons.append(f"{risk.value.upper()} requires human approval (need {need})")
        policy_ids.append("POL-HUMAN-GATE-001")
        if risk == RiskLevel.HIGH and need >= 2:
            policy_ids.append("POL-DUAL-APPROVAL-001")
            reasons.append("HIGH risk dual-control enabled")
    elif risk == RiskLevel.LOW:
        decision = GuardrailDecision.REQUIRE_APPROVAL
        reasons.append("LOW risk but auto-execute disabled — approval required")
        policy_ids.append("POL-NO-AUTO-001")
    else:
        decision = GuardrailDecision.REQUIRE_APPROVAL
        reasons.append("Default human gate")
        policy_ids.append("POL-DEFAULT-GATE-001")

    return GuardrailVerdict(
        decision=decision,
        risk_level=risk,
        reasons=reasons,
        policy_ids=policy_ids,
        proposal_id=proposal.proposal_id,
        required_approvals=required_approvals_for(risk, pack)
        if decision == GuardrailDecision.REQUIRE_APPROVAL
        else 0,
    )
