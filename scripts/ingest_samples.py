#!/usr/bin/env python
"""Ingest sample events against a running API (default http://localhost:8000)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "sample_events" / "events.json"
API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def main() -> None:
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    with httpx.Client(timeout=60.0) as client:
        for event in events:
            resp = client.post(f"{API.rstrip('/')}/v1/incidents/ingest", json=event)
            resp.raise_for_status()
            body = resp.json()
            print(f"[{body['status']}] {body['incident_id']} :: {event['title']}")
            case = body["case"]
            print(f"  proposals={len(case['proposals'])} verdicts={len(case['verdicts'])}")


if __name__ == "__main__":
    main()
