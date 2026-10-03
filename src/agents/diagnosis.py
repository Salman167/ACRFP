"""Diagnosis agent — reliability root-cause + runbook RAG (local corpus first)."""

from __future__ import annotations

from pathlib import Path

from agents.llm import chat_json
from shared.models import DiagnosisResult, IncidentEvent

RUNBOOK_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"


def _load_runbooks() -> list[tuple[str, str]]:
    if not RUNBOOK_DIR.exists():
        return []
    items: list[tuple[str, str]] = []
    for path in sorted(RUNBOOK_DIR.glob("*.md")):
        items.append((path.stem, path.read_text(encoding="utf-8")))
    return items


def _keyword_match(event: IncidentEvent, runbooks: list[tuple[str, str]]) -> list[str]:
    blob = f"{event.title} {event.description} {event.resource or ''}".lower()
    hits: list[str] = []
    for name, body in runbooks:
        tokens = set(name.lower().replace("_", " ").split()) | {
            w for w in ("oom", "cpu", "memory", "crash", "latency", "disk", "cost", "idle") if w in body.lower()
        }
        if any(t in blob for t in tokens if len(t) > 2):
            hits.append(name)
    return hits[:5]


def diagnose(event: IncidentEvent) -> DiagnosisResult:
    runbooks = _load_runbooks()
    related = _keyword_match(event, runbooks)

    llm_out = chat_json(
        system=(
            "You are a Kubernetes/Azure reliability diagnosis agent. "
            "Return JSON with keys: summary, root_cause_hypotheses (array), "
            "related_runbooks (array), confidence (0-1)."
        ),
        user=event.model_dump_json(),
    )
    if isinstance(llm_out, dict) and "summary" in llm_out:
        return DiagnosisResult(
            summary=str(llm_out["summary"]),
            root_cause_hypotheses=[str(x) for x in llm_out.get("root_cause_hypotheses", [])],
            related_runbooks=[str(x) for x in llm_out.get("related_runbooks", related)],
            confidence=float(llm_out.get("confidence", 0.6)),
        )

    # Deterministic local fallback — still demoable without LLM keys.
    hypotheses: list[str] = []
    metrics = event.metrics or {}
    if metrics.get("restarts", 0) and int(metrics.get("restarts", 0)) > 3:
        hypotheses.append("CrashLoopBackOff / repeated container restarts")
    if metrics.get("memory_pct", 0) and float(metrics.get("memory_pct", 0)) > 90:
        hypotheses.append("Memory pressure / possible OOMKill")
    if metrics.get("cpu_pct", 0) and float(metrics.get("cpu_pct", 0)) > 90:
        hypotheses.append("CPU saturation causing latency or throttling")
    if not hypotheses:
        hypotheses.append("Insufficient signals — correlate logs, events, and recent deploys")

    return DiagnosisResult(
        summary=f"Diagnosis for '{event.title}': likely reliability issue in {event.namespace or 'cluster'}.",
        root_cause_hypotheses=hypotheses,
        related_runbooks=related,
        confidence=0.55 if hypotheses else 0.3,
    )
