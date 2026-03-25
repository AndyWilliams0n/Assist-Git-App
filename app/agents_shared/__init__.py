from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents_shared.types import AgentConfig


def load_agent_configs() -> dict[str, AgentConfig]:
    from app.agents_cli_agent.config import CONFIG as cli_agent_config
    from app.agents_code_builder.config import CONFIG as code_builder_config
    from app.agents_code_review.config import CONFIG as code_review_config
    from app.agents_logging_agent.config import CONFIG as logging_agent_config
    from app.agents_orchestrator.config import CONFIG as orchestrator_config
    from app.agents_planner.config import CONFIG as planner_config
    from app.agents_research.config import CONFIG as research_config

    return {
        "orchestrator_codex": orchestrator_config,
        "planner_codex": planner_config,
        "research_codex": research_config,
        "code_builder_codex": code_builder_config,
        "code_reviewer_codex": code_review_config,
        "cli_runner_codex": cli_agent_config,
        "logging_agent_codex": logging_agent_config,
    }


def build_worker_agents(
    resolve_model: Callable[[str | None], str | None],
    factory: Callable[..., Any],
) -> dict[str, Any]:
    agents: dict[str, Any] = {}
    for key, config in load_agent_configs().items():
        agents[key] = factory(
            name=config.name,
            provider=config.provider,
            model=resolve_model(config.settings_key),
            max_tokens=config.max_tokens,
            system_prompt=config.system_prompt,
        )
    return agents


__all__ = ["build_worker_agents", "load_agent_configs"]
