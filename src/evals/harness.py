"""
Offline eval harness — scores the *system*, not LLM self-rating.

Interview talking point:
- Golden incidents are fixtures with expected routing / action types / verdicts.
- Same runner is used by pytest, CLI, and POST /v1/evals/run.
- When Foundry is on, re-run the suite and compare mock vs Claude quality.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from orchestrator.graph import run_incident
from shared.config import get_settings
from shared.models import ActionProposal, GuardrailVerdict, utc_now

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "data" / "evals" / "golden_cases.yaml"


def load_golden_cases(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or GOLDEN_PATH
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    cases = data.get("cases") or []
    if not cases:
        raise ValueError(f"No golden cases found in {target}")
    return cases


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def evaluate_result(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    expect = case.get("expect") or {}
    checks: list[dict[str, Any]] = []

    proposals_raw = result.get("proposals") or []
    verdicts_raw = result.get("verdicts") or []
    notes = " ".join(result.get("notes") or [])
    diagnosis = result.get("diagnosis") or {}
    cost = result.get("cost")

    valid_proposals = 0
    action_types: set[str] = set()
    for raw in proposals_raw:
        try:
            prop = ActionProposal.model_validate(raw)
            valid_proposals += 1
            action_types.add(prop.action_type.value)
        except Exception:
            continue

    decisions: set[str] = set()
    max_required = 0
    for raw in verdicts_raw:
        try:
            verdict = GuardrailVerdict.model_validate(raw)
            decisions.add(verdict.decision.value)
            max_required = max(max_required, verdict.required_approvals)
        except Exception:
            continue

    checks.append(
        _check(
            "proposals_present",
            valid_proposals > 0,
            f"{valid_proposals} valid ActionProposal(s)",
        )
    )

    wanted_actions = set(_as_list(expect.get("action_types")))
    if wanted_actions:
        missing = sorted(wanted_actions - action_types)
        checks.append(
            _check(
                "action_types",
                not missing,
                f"got={sorted(action_types)} missing={missing}",
            )
        )

    wanted_decisions = set(_as_list(expect.get("decisions")))
    if wanted_decisions:
        overlap = wanted_decisions & decisions
        checks.append(
            _check(
                "guardrail_decisions",
                bool(overlap),
                f"got={sorted(decisions)} expected any of {sorted(wanted_decisions)}",
            )
        )

    wanted_status = set(_as_list(expect.get("statuses")))
    status = str(result.get("status") or "")
    if wanted_status:
        checks.append(
            _check(
                "status",
                status in wanted_status,
                f"got={status} expected one of {sorted(wanted_status)}",
            )
        )

    for specialist in _as_list(expect.get("specialists")):
        if specialist == "diagnosis":
            ok = bool(diagnosis) or "diagnosis:" in notes
            checks.append(_check("specialist_diagnosis", ok, "diagnosis node ran"))
        elif specialist == "cost":
            ok = bool(cost) or "cost:" in notes
            checks.append(_check("specialist_cost", ok, "cost node ran"))

    min_approvals = expect.get("min_required_approvals")
    if min_approvals is not None:
        need = int(min_approvals)
        checks.append(
            _check(
                "required_approvals",
                max_required >= need,
                f"max required_approvals={max_required} need>={need}",
            )
        )

    runbook_token = expect.get("runbook_contains")
    if runbook_token:
        related = " ".join(diagnosis.get("related_runbooks") or []).lower()
        token = str(runbook_token).lower()
        checks.append(
            _check(
                "runbook_grounding",
                token in related,
                f"related_runbooks={related or '(none)'} token={token}",
            )
        )

    passed = all(c["passed"] for c in checks)
    return {
        "id": case.get("id"),
        "description": case.get("description"),
        "passed": passed,
        "status": status,
        "action_types": sorted(action_types),
        "decisions": sorted(decisions),
        "checks": checks,
        "checks_passed": sum(1 for c in checks if c["passed"]),
        "checks_total": len(checks),
    }


def run_eval_suite(path: Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    started = utc_now()
    cases = load_golden_cases(path)
    reports: list[dict[str, Any]] = []

    for case in cases:
        event = dict(case.get("event") or {})
        result = run_incident(event)
        reports.append(evaluate_result(case, result))

    checks_passed = sum(r["checks_passed"] for r in reports)
    checks_total = sum(r["checks_total"] for r in reports)
    cases_passed = sum(1 for r in reports if r["passed"])
    score = (checks_passed / checks_total) if checks_total else 0.0

    return {
        "suite": "acrfp-golden",
        "passed": cases_passed == len(reports) and checks_total > 0,
        "score": round(score, 4),
        "cases_passed": cases_passed,
        "cases_total": len(reports),
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "llm_provider": settings.llm_provider,
        "policy_pack": settings.policy_pack,
        "evaluated_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "cases": reports,
    }
