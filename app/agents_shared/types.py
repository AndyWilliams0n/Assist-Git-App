from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    name: str
    provider: str
    settings_key: str | None
    system_prompt: str
    max_tokens: int | None = None
