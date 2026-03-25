from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    name: str = "Pipeline Agent"
    heartbeat_name: str = "Pipeline Heartbeat Agent"
    group: str = "agents_pipeline"
    role: str = "pipeline"
    description: str = (
        "Autonomous Jira pipeline runner that schedules heartbeat execution, "
        "generates task briefs/specs/checklists, and hands work to the code builder outside chat."
    )


CONFIG = PipelineConfig()

AUTONOMY_RULE = (
    "Under no circumstances ask clarifying questions. "
    "You must make reasonable assumptions and proceed autonomously. "
    "If assumptions are needed, document them in your output and continue execution."
)

PIPELINE_POLL_SECONDS = 5
CODEX_TIMEOUT_SECONDS = 3600
