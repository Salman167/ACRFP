"""Optional webhook notifier for pending approvals (Teams/Slack-compatible JSON)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from shared.config import get_settings

log = structlog.get_logger()


def notify_pending_approval(payload: dict[str, Any]) -> None:
    """Fire-and-forget POST to NOTIFY_WEBHOOK_URL if configured."""

    url = (get_settings().notify_webhook_url or "").strip()
    if not url:
        return
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
        log.info("webhook_notified", url=url)
    except Exception as exc:
        log.warning("webhook_failed", error=str(exc), url=url)
