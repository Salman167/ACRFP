"""Unit tests for the interview-critical guardrail policy."""

import os

os.environ["POLICY_PACK"] = "local"
os.environ["LLM_PROVIDER"] = "mock"

from shared.config import get_settings

get_settings.cache_clear()

from guardrail.policy import classify_risk, decide, load_policy_pack, required_approvals_for, reload_policy_pack
from shared.models import ActionProposal, ActionType, GuardrailDecision, RiskLevel

reload_policy_pack()


def test_restart_pod_is_low_and_allowable():
    p = ActionProposal(
        action_type=ActionType.RESTART_POD,
        target="payments-api",
        namespace="payments",
        rationale="restarts",
        expected_impact="heal",
        risk_hint=RiskLevel.LOW,
    )
    risk, _, _ = classify_risk(p)
    assert risk == RiskLevel.LOW
    assert decide(p).decision == GuardrailDecision.ALLOW


def test_scale_to_zero_escalates_to_high():
    p = ActionProposal(
        action_type=ActionType.SCALE_DEPLOYMENT,
        target="payments-api",
        namespace="payments",
        parameters={"replicas": 0, "current_replicas": 3},
        rationale="oops",
        expected_impact="outage",
        risk_hint=RiskLevel.LOW,
    )
    risk, reasons, _ = classify_risk(p)
    assert risk == RiskLevel.HIGH
    assert any("Scaling to 0" in r for r in reasons)


def test_protected_namespace_escalates():
    p = ActionProposal(
        action_type=ActionType.RESTART_POD,
        target="coredns",
        namespace="kube-system",
        rationale="test",
        expected_impact="test",
        risk_hint=RiskLevel.LOW,
    )
    risk, _, _ = classify_risk(p)
    assert risk == RiskLevel.HIGH
    v = decide(p)
    assert v.decision == GuardrailDecision.REQUIRE_APPROVAL
    assert v.required_approvals == 2


def test_delete_namespace_denied_as_critical():
    p = ActionProposal(
        action_type=ActionType.DELETE_NAMESPACE,
        target="payments",
        namespace="payments",
        rationale="cleanup",
        expected_impact="destroy",
        reversible=False,
        risk_hint=RiskLevel.LOW,
    )
    v = decide(p)
    assert v.risk_level == RiskLevel.CRITICAL
    assert v.decision == GuardrailDecision.DENY


def test_agent_hint_cannot_downgrade():
    p = ActionProposal(
        action_type=ActionType.DELETE_WORKLOAD,
        target="payments-api",
        namespace="payments",
        rationale="remove",
        expected_impact="gone",
        reversible=False,
        risk_hint=RiskLevel.LOW,
    )
    risk, _, _ = classify_risk(p)
    assert risk == RiskLevel.HIGH


def test_yaml_policy_pack_loads():
    pack = load_policy_pack("local")
    assert pack.get("policy_pack") == "local"
    assert "restart_pod" in pack.get("base_risk", {})


def test_high_requires_dual_approval():
    assert required_approvals_for(RiskLevel.HIGH) == 2
    assert required_approvals_for(RiskLevel.MEDIUM) == 1


def test_region_lock_denies_outside_allow_list():
    p = ActionProposal(
        action_type=ActionType.RESTART_POD,
        target="payments-api",
        namespace="payments",
        region="us-east-1",
        rationale="test",
        expected_impact="test",
        risk_hint=RiskLevel.LOW,
    )
    v = decide(p)
    assert v.decision == GuardrailDecision.DENY
    assert "POL-REGION-LOCK-001" in v.policy_ids
