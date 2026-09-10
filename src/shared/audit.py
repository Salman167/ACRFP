"""Append-only audit trail for compliance demos (EU/Gulf interview talking point).

Interview line: every autonomous decision is reconstructable — who proposed,
what policy said, who approved, and what executed.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from shared.models import new_id, utc_now


class AuditEvent(BaseModel):
    audit_id: str = Field(default_factory=lambda: new_id("aud"))
    timestamp: datetime = Field(default_factory=utc_now)
    incident_id: str | None = None
    event_type: str  # incident.ingested | guardrail.verdict | approval.decision | execution.result
    actor: str = "system"
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class AuditStore:
    """In-memory + optional JSONL file persistence (local/demo)."""

    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._events: list[AuditEvent] = []
        root = Path(__file__).resolve().parents[2]
        self._path = path or (root / "data" / "runtime" / "audit.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self._events.append(AuditEvent.model_validate_json(line))
            except Exception:
                continue

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._lock:
            self._events.append(event)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        return event

    def record(
        self,
        event_type: str,
        summary: str,
        *,
        incident_id: str | None = None,
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        return self.append(
            AuditEvent(
                event_type=event_type,
                summary=summary,
                incident_id=incident_id,
                actor=actor,
                details=details or {},
            )
        )

    def list(
        self,
        *,
        incident_id: str | None = None,
        limit: int = 500,
    ) -> list[AuditEvent]:
        with self._lock:
            items = list(self._events)
        if incident_id:
            items = [e for e in items if e.incident_id == incident_id]
        return list(reversed(items[-limit:]))

    def export_json(self, incident_id: str | None = None) -> str:
        events = self.list(incident_id=incident_id, limit=10_000)
        return json.dumps([e.model_dump(mode="json") for e in events], indent=2)

    def export_csv(self, incident_id: str | None = None) -> str:
        events = self.list(incident_id=incident_id, limit=10_000)
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=["audit_id", "timestamp", "incident_id", "event_type", "actor", "summary"],
        )
        writer.writeheader()
        for e in events:
            writer.writerow(
                {
                    "audit_id": e.audit_id,
                    "timestamp": e.timestamp.isoformat(),
                    "incident_id": e.incident_id or "",
                    "event_type": e.event_type,
                    "actor": e.actor,
                    "summary": e.summary,
                }
            )
        return buf.getvalue()


_STORE: AuditStore | None = None


def get_audit_store() -> AuditStore:
    global _STORE
    if _STORE is None:
        _STORE = AuditStore()
    return _STORE
