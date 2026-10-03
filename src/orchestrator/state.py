"""LangGraph shared state for one incident run.

Interview talking point: state is explicit and typed — not a chat blob.
Each node writes only the fields it owns; routing is deterministic from event_type
plus what has already been filled.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from shared.models import (
    ActionProposal,
    CostFinding,
    DiagnosisResult,
    ExecutionResult,
    GuardrailVerdict,
    IncidentEvent,
)


class GraphState(TypedDict, total=False):
    incident_id: str
    event: dict[str, Any]  # IncidentEvent as dict for LangGraph serialization
    route_plan: list[str]
    diagnosis: dict[str, Any] | None
    cost: dict[str, Any] | None
    proposals: list[dict[str, Any]]
    verdicts: list[dict[str, Any]]
    auto_execute: list[dict[str, Any]]
    pending_approval: list[dict[str, Any]]
    denied: list[dict[str, Any]]
    executions: list[dict[str, Any]]
    status: str
    notes: Annotated[list[str], operator.add]


def event_from_state(state: GraphState) -> IncidentEvent:
    return IncidentEvent.model_validate(state["event"])


def diagnosis_from_state(state: GraphState) -> DiagnosisResult | None:
    raw = state.get("diagnosis")
    return DiagnosisResult.model_validate(raw) if raw else None


def cost_from_state(state: GraphState) -> CostFinding | None:
    raw = state.get("cost")
    return CostFinding.model_validate(raw) if raw else None


def proposals_from_state(state: GraphState) -> list[ActionProposal]:
    return [ActionProposal.model_validate(p) for p in state.get("proposals") or []]


def verdicts_from_state(state: GraphState) -> list[GuardrailVerdict]:
    return [GuardrailVerdict.model_validate(v) for v in state.get("verdicts") or []]


def executions_from_state(state: GraphState) -> list[ExecutionResult]:
    return [ExecutionResult.model_validate(e) for e in state.get("executions") or []]
