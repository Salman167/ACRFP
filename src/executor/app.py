"""Executor — applies approved proposals via dry-run local mock or real backends."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from shared.config import get_settings
from shared.models import ActionProposal, ActionType, ExecutionResult

app = FastAPI(title="ACRFP Executor", version="0.1.0")


class ExecuteRequest(BaseModel):
    proposal: ActionProposal
    dry_run: bool = True


def _execute_local(proposal: ActionProposal, dry_run: bool) -> ExecutionResult:
    """Local mock: log the intended kubectl/ARM effect without touching a cluster."""

    action = proposal.action_type
    details: dict[str, Any] = {
        "cluster": get_settings().cluster_name,
        "action": action.value,
        "target": proposal.target,
        "namespace": proposal.namespace,
        "parameters": proposal.parameters,
    }

    if action == ActionType.RESTART_POD:
        cmd = f"kubectl rollout restart deployment/{proposal.target} -n {proposal.namespace}"
    elif action == ActionType.SCALE_DEPLOYMENT:
        replicas = proposal.parameters.get("replicas")
        cmd = f"kubectl scale deployment/{proposal.target} -n {proposal.namespace} --replicas={replicas}"
    elif action == ActionType.APPLY_HPA:
        cmd = f"kubectl autoscale deployment/{proposal.target} -n {proposal.namespace} ..."
    elif action == ActionType.STOP_IDLE_RESOURCE:
        cmd = f"az vm deallocate --ids {proposal.target}  # or ARM equivalent"
    else:
        cmd = f"planned:{action.value}"

    details["planned_command"] = cmd
    return ExecutionResult(
        proposal_id=proposal.proposal_id,
        success=True,
        dry_run=dry_run,
        message=("DRY-RUN: " if dry_run else "APPLIED: ") + cmd,
        details=details,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "executor"}


@app.post("/v1/execute", response_model=ExecutionResult)
def execute(req: ExecuteRequest) -> ExecutionResult:
    settings = get_settings()
    # Production hook: swap to real kubectl/ARM when acrfp_mode=azure and dry_run=False.
    if settings.acrfp_mode == "azure" and not req.dry_run:
        # Intentionally not implemented yet — Week 4+ when AKS + Key Vault are wired.
        return ExecutionResult(
            proposal_id=req.proposal.proposal_id,
            success=False,
            dry_run=False,
            message="Live Azure execution not enabled yet — use dry_run or local mode",
            details={},
        )
    return _execute_local(req.proposal, dry_run=req.dry_run)
