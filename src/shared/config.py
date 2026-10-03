"""Shared configuration for local and Azure modes."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    acrfp_mode: str = "local"
    llm_provider: str = "mock"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    azure_foundry_endpoint: str = ""
    azure_foundry_api_key: str = ""
    azure_foundry_deployment: str = "claude-sonnet-4-5"

    guardrail_url: str = "http://localhost:8001"
    executor_url: str = "http://localhost:8002"
    api_url: str = "http://localhost:8000"

    auto_execute_low_risk: bool = True
    require_human_for_medium: bool = True
    deny_critical_by_default: bool = True
    policy_pack: str = "local"  # local | prod  → data/policies/{pack}.yaml

    cluster_name: str = "local-dev"
    cloud_provider: str = "azure"
    notify_webhook_url: str = ""  # optional Teams/Slack incoming webhook


@lru_cache
def get_settings() -> Settings:
    return Settings()
