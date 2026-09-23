"""API gateway — ingest events, run LangGraph, human approval queue, audit export."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from pathlib import Path

from evals.harness import load_golden_cases, run_eval_suite
from orchestrator.graph import run_incident
from shared.audit import AuditEvent, get_audit_store
from shared.models import (
    ApprovalDecisionEntry,
    ApprovalRecord,
    IncidentCase,
    IncidentEvent,
    RiskLevel,
    new_id,
)

app = FastAPI(
    title="ACRFP API",
    description="Agentic Cloud Reliability & FinOps Platform",
    version="0.3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/ui", include_in_schema=False)
def approval_console() -> FileResponse:
    """Simple human-approval UI for demos (Week 2)."""
    return FileResponse(STATIC_DIR / "index.html")

# In-memory store for local/demo. Swap to Postgres/Cosmos in production.
CASES: dict[str, IncidentCase] = {}
APPROVALS: dict[str, ApprovalRecord] = {}
LAST_EVAL_REPORT: dict[str, Any] | None = None


class IngestResponse(BaseModel):
    incident_id: str
    status: str
    case: IncidentCase


class ApprovalDecision(BaseModel):
    decision: str = Field(description="approved | rejected")
    decided_by: str = "human"
    comment: str | None = None


def _case_from_graph(result: dict[str, Any], event: IncidentEvent) -> IncidentCase:
    from shared.models import (
        ActionProposal,
        CostFinding,
        DiagnosisResult,
        ExecutionResult,
        GuardrailVerdict,
    )

    audit = get_audit_store()
    incident_id = result.get("incident_id") or new_id("inc")
    proposals = [ActionProposal.model_validate(p) for p in result.get("proposals") or []]
    verdicts = [GuardrailVerdict.model_validate(v) for v in result.get("verdicts") or []]
    executions = [ExecutionResult.model_validate(e) for e in result.get("executions") or []]

    diagnosis = result.get("diagnosis")
    cost = result.get("cost")

    case = IncidentCase(
        incident_id=incident_id,
        event=event,
        diagnosis=DiagnosisResult.model_validate(diagnosis) if diagnosis else None,
        cost=CostFinding.model_validate(cost) if cost else None,
        proposals=proposals,
        verdicts=verdicts,
        executions=executions,
        status=result.get("status", "open"),
        notes=list(result.get("notes") or []),
    )

    audit.record(
        "incident.ingested",
        f"Ingested '{event.title}' → status={case.status}",
        incident_id=incident_id,
        actor="api",
        details={"event_type": event.event_type.value, "resource": event.resource},
    )

    verdict_by_proposal = {v.proposal_id: v for v in verdicts}
    for v in verdicts:
        audit.record(
            "guardrail.verdict",
            f"{v.decision.value} risk={v.risk_level.value} for {v.proposal_id}",
            incident_id=incident_id,
            actor="guardrail",
            details={
                "proposal_id": v.proposal_id,
                "decision": v.decision.value,
                "risk_level": v.risk_level.value,
                "policy_ids": v.policy_ids,
                "required_approvals": v.required_approvals,
            },
        )

    for prop in result.get("pending_approval") or []:
        v = verdict_by_proposal.get(prop["proposal_id"])
        required = v.required_approvals if v and v.required_approvals else 1
        risk = v.risk_level if v else RiskLevel.MEDIUM
        apr = ApprovalRecord(
            proposal_id=prop["proposal_id"],
            incident_id=incident_id,
            risk_level=risk,
            required_approvals=required,
        )
        APPROVALS[apr.approval_id] = apr
        case.approvals.append(apr)
        audit.record(
            "approval.requested",
            f"Approval required for {apr.proposal_id} (need {required})",
            incident_id=incident_id,
            actor="guardrail",
            details={"approval_id": apr.approval_id, "required_approvals": required},
        )
        from shared.notify import notify_pending_approval

        notify_pending_approval(
            {
                "text": f"ACRFP approval needed: {event.title}",
                "approval_id": apr.approval_id,
                "incident_id": incident_id,
                "proposal_id": apr.proposal_id,
                "risk_level": risk.value if hasattr(risk, "value") else str(risk),
                "required_approvals": required,
                "ui": "/ui",
            }
        )

    for ex in executions:
        audit.record(
            "execution.result",
            ex.message,
            incident_id=incident_id,
            actor="executor",
            details={
                "proposal_id": ex.proposal_id,
                "success": ex.success,
                "dry_run": ex.dry_run,
            },
        )

    for denied in result.get("denied") or []:
        audit.record(
            "guardrail.denied",
            f"Denied proposal {denied.get('proposal_id')}",
            incident_id=incident_id,
            actor="guardrail",
            details=denied,
        )

    return case


def _execute_proposal(case: IncidentCase, proposal_id: str, actor: str) -> None:
    import httpx

    from shared.config import get_settings
    from shared.models import ExecutionResult

    audit = get_audit_store()
    prop = next((p for p in case.proposals if p.proposal_id == proposal_id), None)
    if not prop:
        return
    settings = get_settings()
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"{settings.executor_url.rstrip('/')}/v1/execute",
                json={
                    "proposal": prop.model_dump(mode="json"),
                    "dry_run": settings.acrfp_mode == "local",
                },
            )
            resp.raise_for_status()
            result = ExecutionResult.model_validate(resp.json())
            case.executions.append(result)
            case.status = "resolved"
            case.notes.append(f"human approved {proposal_id}")
            audit.record(
                "execution.result",
                result.message,
                incident_id=case.incident_id,
                actor=actor,
                details={
                    "proposal_id": proposal_id,
                    "success": result.success,
                    "dry_run": result.dry_run,
                },
            )
    except Exception as exc:
        case.notes.append(f"approved but executor failed: {exc}")
        case.status = "blocked"
        audit.record(
            "execution.failed",
            str(exc),
            incident_id=case.incident_id,
            actor=actor,
            details={"proposal_id": proposal_id},
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.post("/v1/incidents/ingest", response_model=IngestResponse)
def ingest(event: IncidentEvent) -> IngestResponse:
    result = run_incident(event.model_dump(mode="json"))
    case = _case_from_graph(result, event)
    CASES[case.incident_id] = case
    return IngestResponse(incident_id=case.incident_id, status=case.status, case=case)


@app.get("/v1/incidents", response_model=list[IncidentCase])
def list_incidents() -> list[IncidentCase]:
    return sorted(CASES.values(), key=lambda c: c.created_at, reverse=True)


@app.get("/v1/incidents/{incident_id}", response_model=IncidentCase)
def get_incident(incident_id: str) -> IncidentCase:
    case = CASES.get(incident_id)
    if not case:
        raise HTTPException(status_code=404, detail="incident not found")
    return case


@app.get("/v1/approvals/pending", response_model=list[ApprovalRecord])
def pending_approvals() -> list[ApprovalRecord]:
    return [a for a in APPROVALS.values() if a.status == "pending"]


@app.post("/v1/approvals/{approval_id}/decide", response_model=ApprovalRecord)
def decide_approval(approval_id: str, body: ApprovalDecision) -> ApprovalRecord:
    apr = APPROVALS.get(approval_id)
    if not apr:
        raise HTTPException(status_code=404, detail="approval not found")
    if apr.status != "pending":
        raise HTTPException(status_code=400, detail=f"already {apr.status}")

    if body.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be approved|rejected")

    audit = get_audit_store()

    # Dual control: same person cannot approve twice; need N distinct approvers.
    if body.decision == "approved":
        existing = {d.decided_by.lower() for d in apr.decisions if d.decision == "approved"}
        if body.decided_by.lower() in existing:
            raise HTTPException(
                status_code=400,
                detail="dual-control: same approver cannot count twice",
            )

    entry = ApprovalDecisionEntry(
        decided_by=body.decided_by,
        decision=body.decision,
        comment=body.comment,
    )
    apr.decisions.append(entry)
    apr.decided_by = body.decided_by
    apr.decided_at = datetime.now(timezone.utc)
    apr.comment = body.comment

    audit.record(
        "approval.decision",
        f"{body.decision} by {body.decided_by} on {apr.proposal_id}",
        incident_id=apr.incident_id,
        actor=body.decided_by,
        details={
            "approval_id": approval_id,
            "decision": body.decision,
            "collected": len([d for d in apr.decisions if d.decision == "approved"]),
            "required": apr.required_approvals,
        },
    )

    if body.decision == "rejected":
        apr.status = "rejected"
    else:
        approved_count = len([d for d in apr.decisions if d.decision == "approved"])
        if approved_count >= apr.required_approvals:
            apr.status = "approved"
        else:
            apr.status = "pending"
            apr.comment = (
                f"waiting for dual approval "
                f"({approved_count}/{apr.required_approvals})"
            )

    APPROVALS[approval_id] = apr

    case = CASES.get(apr.incident_id)
    if case:
        case.approvals = [apr if a.approval_id == approval_id else a for a in case.approvals]
        if apr.status == "approved":
            _execute_proposal(case, apr.proposal_id, actor=body.decided_by)
        elif apr.status == "rejected":
            case.notes.append(f"human rejected {apr.proposal_id}")
            if not any(a.status == "pending" for a in case.approvals):
                case.status = "blocked"
        else:
            case.notes.append(
                f"partial approval {apr.proposal_id}: "
                f"{len([d for d in apr.decisions if d.decision == 'approved'])}/"
                f"{apr.required_approvals}"
            )
            case.status = "awaiting_approval"
        case.updated_at = datetime.now(timezone.utc)
        CASES[case.incident_id] = case

    return apr


@app.get("/v1/audit", response_model=list[AuditEvent])
def list_audit(
    incident_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
) -> list[AuditEvent]:
    return get_audit_store().list(incident_id=incident_id, limit=limit)


@app.get("/v1/incidents/{incident_id}/audit", response_model=list[AuditEvent])
def incident_audit(incident_id: str) -> list[AuditEvent]:
    if incident_id not in CASES and not get_audit_store().list(incident_id=incident_id, limit=1):
        raise HTTPException(status_code=404, detail="incident not found")
    return get_audit_store().list(incident_id=incident_id, limit=2000)


@app.get("/v1/audit/export")
def export_audit(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    incident_id: str | None = None,
) -> Response:
    store = get_audit_store()
    if format == "csv":
        return PlainTextResponse(
            store.export_csv(incident_id=incident_id),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=acrfp-audit.csv"},
        )
    return Response(
        content=store.export_json(incident_id=incident_id),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=acrfp-audit.json"},
    )


@app.get("/v1/evals/cases")
def list_eval_cases() -> dict[str, Any]:
    """List golden incidents used by the eval harness (no graph run)."""
    cases = load_golden_cases()
    return {
        "suite": "acrfp-golden",
        "count": len(cases),
        "cases": [
            {
                "id": c.get("id"),
                "description": c.get("description"),
                "expect": c.get("expect") or {},
            }
            for c in cases
        ],
    }


@app.get("/v1/evals")
def get_last_eval() -> dict[str, Any]:
    if LAST_EVAL_REPORT is None:
        return {"suite": "acrfp-golden", "ran": False, "message": "No eval run yet. POST /v1/evals/run"}
    return LAST_EVAL_REPORT


@app.post("/v1/evals/run")
def run_evals() -> dict[str, Any]:
    """Score the LangGraph + guardrail pipeline against golden incidents."""
    global LAST_EVAL_REPORT
    report = run_eval_suite()
    LAST_EVAL_REPORT = report
    get_audit_store().record(
        "eval.suite.completed",
        (
            f"golden eval score={report['score']} "
            f"{report['cases_passed']}/{report['cases_total']} cases"
        ),
        actor="evals",
        details={
            "score": report["score"],
            "passed": report["passed"],
            "llm_provider": report["llm_provider"],
            "failed": [c["id"] for c in report["cases"] if not c["passed"]],
        },
    )
    return report
