"""HTTP guardrail service — agents call this; they never self-authorize."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from guardrail.policy import decide
from shared.models import ActionProposal, GuardrailVerdict

app = FastAPI(title="ACRFP Guardrail Proxy", version="0.1.0")


class EvaluateRequest(BaseModel):
    proposal: ActionProposal


class EvaluateBatchRequest(BaseModel):
    proposals: list[ActionProposal]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "guardrail"}


@app.post("/v1/evaluate", response_model=GuardrailVerdict)
def evaluate(req: EvaluateRequest) -> GuardrailVerdict:
    return decide(req.proposal)


@app.post("/v1/evaluate/batch", response_model=list[GuardrailVerdict])
def evaluate_batch(req: EvaluateBatchRequest) -> list[GuardrailVerdict]:
    return [decide(p) for p in req.proposals]
