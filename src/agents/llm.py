"""LLM helper with mock fallback so the platform runs without API keys."""

from __future__ import annotations

import json
import re
from typing import Any

from shared.config import get_settings


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def chat_json(system: str, user: str) -> dict[str, Any] | list[Any] | None:
    """Return parsed JSON from the configured provider, or None to use rules."""

    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "mock":
        return None

    try:
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=settings.openai_api_key or None)
            resp = llm.invoke(
                [
                    {"role": "system", "content": system + "\nRespond with valid JSON only."},
                    {"role": "user", "content": user},
                ]
            )
            return _extract_json(str(resp.content))

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(
                model="claude-sonnet-4-5",
                temperature=0,
                api_key=settings.anthropic_api_key or None,
            )
            resp = llm.invoke(
                [
                    {"role": "system", "content": system + "\nRespond with valid JSON only."},
                    {"role": "user", "content": user},
                ]
            )
            return _extract_json(str(resp.content))

        if provider == "azure_foundry":
            # Claude / OpenAI-compatible endpoint via Microsoft Foundry model deployment.
            from langchain_openai import ChatOpenAI

            if not settings.azure_foundry_endpoint or not settings.azure_foundry_api_key:
                return None
            llm = ChatOpenAI(
                model=settings.azure_foundry_deployment,
                temperature=0,
                api_key=settings.azure_foundry_api_key,
                base_url=settings.azure_foundry_endpoint.rstrip("/") + "/openai/v1",
            )
            resp = llm.invoke(
                [
                    {"role": "system", "content": system + "\nRespond with valid JSON only."},
                    {"role": "user", "content": user},
                ]
            )
            return _extract_json(str(resp.content))
    except Exception:
        return None

    return None
