"""Loads config.yaml and expands ${ENV_VAR} references against the environment."""
from __future__ import annotations

import os
import re
import yaml
from dataclasses import dataclass, field
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """Recursively replace ${VAR} with os.environ['VAR']. Leaves it as None
    (not the literal string) if the variable is unset, so callers can detect
    missing secrets instead of silently sending the literal '${VAR}' to an API."""
    if isinstance(value, str):
        match = _ENV_PATTERN.fullmatch(value.strip())
        if match:
            return os.environ.get(match.group(1))
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class AgentSettings:
    max_iterations: int = 50
    max_retries_per_step: int = 4
    retry_backoff_seconds: float = 2.0
    stop_on_unrecoverable: bool = True
    log_file: str = "/opt/data/agent.log"


@dataclass
class Config:
    name: str = "Tharun AI Assistant"
    provider: str = "gemini"
    model: str = "gemini-3.1-flash-lite"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.4
    agent: AgentSettings = field(default_factory=AgentSettings)
    mcp_servers: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        raw = _expand_env(raw)

        agent_raw = raw.get("agent", {}) or {}
        agent_settings = AgentSettings(
            max_iterations=agent_raw.get("max_iterations", 50),
            max_retries_per_step=agent_raw.get("max_retries_per_step", 4),
            retry_backoff_seconds=agent_raw.get("retry_backoff_seconds", 2.0),
            stop_on_unrecoverable=agent_raw.get("stop_on_unrecoverable", True),
            log_file=agent_raw.get("log_file", "/opt/data/agent.log"),
        )

        return cls(
            name=raw.get("name", "Tharun AI Assistant"),
            provider=raw.get("provider", "gemini"),
            model=raw.get("model", "gemini-3.1-flash-lite"),
            api_key=raw.get("api_key"),
            base_url=raw.get("base_url"),
            temperature=raw.get("temperature", 0.4),
            agent=agent_settings,
            mcp_servers=raw.get("mcp_servers", []) or [],
        )
