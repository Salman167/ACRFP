"""Cost / FinOps agent — anomaly framing over Cost Management-shaped signals."""

from __future__ import annotations

from agents.llm import chat_json
from shared.models import CostFinding, IncidentEvent


def analyze_cost(event: IncidentEvent) -> CostFinding:
    signal = event.cost_signal or {}
    llm_out = chat_json(
        system=(
            "You are a FinOps cost anomaly agent for Azure. "
            "Return JSON with keys: summary, anomaly_detected (bool), "
            "estimated_monthly_impact_usd (number), drivers (array), recommendations (array)."
        ),
        user=event.model_dump_json(),
    )
    if isinstance(llm_out, dict) and "summary" in llm_out:
        return CostFinding(
            summary=str(llm_out["summary"]),
            anomaly_detected=bool(llm_out.get("anomaly_detected", False)),
            estimated_monthly_impact_usd=float(llm_out.get("estimated_monthly_impact_usd", 0)),
            drivers=[str(x) for x in llm_out.get("drivers", [])],
            recommendations=[str(x) for x in llm_out.get("recommendations", [])],
        )

    baseline = float(signal.get("baseline_daily_usd", 0) or 0)
    actual = float(signal.get("actual_daily_usd", 0) or 0)
    idle = bool(signal.get("idle_resource", False))
    sku = signal.get("sku")

    anomaly = False
    impact = 0.0
    drivers: list[str] = []
    recs: list[str] = []

    if baseline > 0 and actual > baseline * 1.4:
        anomaly = True
        impact = (actual - baseline) * 30
        drivers.append(f"Daily spend ${actual:.2f} vs baseline ${baseline:.2f} (+{(actual / baseline - 1) * 100:.0f}%)")
        recs.append("Identify top cost drivers by resource group / meter and rightsize or schedule off-hours")

    if idle:
        anomaly = True
        impact = max(impact, float(signal.get("idle_monthly_usd", 120)))
        drivers.append(f"Idle resource detected{f' ({sku})' if sku else ''}")
        recs.append("Stop or deallocate idle compute; tag owners; add budget alert")

    if not drivers:
        drivers.append("No strong cost anomaly in provided signal")
        recs.append("Continue monitoring with Azure Cost Management + budgets")

    return CostFinding(
        summary=f"Cost analysis for '{event.title}'",
        anomaly_detected=anomaly,
        estimated_monthly_impact_usd=round(impact, 2),
        drivers=drivers,
        recommendations=recs,
    )
