"""Domain models shared across orchestrator, agents, guardrail, and executor.

Interview talking point: every remediating action is a typed Proposal with an
explicit risk class — never free-text "do something to the cluster".
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class EventType(str, Enum):
    RELIABILITY = "reliability"
    COST = "cost"
    MIXED = "mixed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(str, Enum):
    RESTART_POD = "restart_pod"
    SCALE_DEPLOYMENT = "scale_deployment"
    PATCH_RESOURCES = "patch_resources"
    APPLY_HPA = "apply_hpa"
    DRAIN_NODE = "drain_node"
    DELETE_WORKLOAD = "delete_workload"
    DELETE_NAMESPACE = "delete_namespace"
    CHANGE_NETWORK_POLICY = "change_network_policy"
    RIGHTSIZE_SKU = "rightsize_sku"
    STOP_IDLE_RESOURCE = "stop_idle_resource"
    DELETE_RESOURCE_GROUP = "delete_resource_group"
    MODIFY_IAM = "modify_iam"


class GuardrailDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class IncidentEvent(BaseModel):
    """Inbound signal from Event Hub / Service Bus / local mock injector."""

    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: EventType
    source: str = "mock"
    cluster: str = "local-dev"
    region: str = "local"  # sovereign lock: must be in policy allowed_regions
    namespace: str | None = None
    resource: str | None = None
    severity: str = "warning"
    title: str
    description: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    cost_signal: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=utc_now)


class DiagnosisResult(BaseModel):
    summary: str
    root_cause_hypotheses: list[str] = Field(default_factory=list)
    related_runbooks: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class CostFinding(BaseModel):
    summary: str
    anomaly_detected: bool = False
    estimated_monthly_impact_usd: float = 0.0
    drivers: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ActionProposal(BaseModel):
    """Structured remediation the remediation agent must emit (no free-form shell)."""

    proposal_id: str = Field(default_factory=lambda: new_id("prop"))
    action_type: ActionType
    target: str
    namespace: str | None = None
    region: str = "local"
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    expected_impact: str
    reversible: bool = True
    risk_hint: RiskLevel = RiskLevel.MEDIUM


class GuardrailVerdict(BaseModel):
    decision: GuardrailDecision
    risk_level: RiskLevel
    reasons: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    proposal_id: str
    required_approvals: int = 0
    evaluated_at: datetime = Field(default_factory=utc_now)


class ApprovalDecisionEntry(BaseModel):
    decided_by: str
    decision: str  # approved | rejected
    decided_at: datetime = Field(default_factory=utc_now)
    comment: str | None = None


class ApprovalRecord(BaseModel):
    approval_id: str = Field(default_factory=lambda: new_id("apr"))
    proposal_id: str
    incident_id: str
    status: str = "pending"  # pending | approved | rejected
    risk_level: RiskLevel | None = None
    required_approvals: int = 1
    decisions: list[ApprovalDecisionEntry] = Field(default_factory=list)
    decided_by: str | None = None  # last actor (compat)
    decided_at: datetime | None = None
    comment: str | None = None


class ExecutionResult(BaseModel):
    execution_id: str = Field(default_factory=lambda: new_id("exec"))
    proposal_id: str
    success: bool
    dry_run: bool = True
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=utc_now)


class IncidentCase(BaseModel):
    """End-to-end case file produced by one LangGraph run."""

    incident_id: str = Field(default_factory=lambda: new_id("inc"))
    event: IncidentEvent
    diagnosis: DiagnosisResult | None = None
    cost: CostFinding | None = None
    proposals: list[ActionProposal] = Field(default_factory=list)
    verdicts: list[GuardrailVerdict] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    executions: list[ExecutionResult] = Field(default_factory=list)
    status: str = "open"  # open | awaiting_approval | remediating | resolved | blocked
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
