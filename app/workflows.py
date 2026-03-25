from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class WorkflowStep:
    tier: int
    agents: List[str]
    description: str


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    label: str
    description: str
    steps: List[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "steps": [
                {
                    "tier": step.tier,
                    "agents": step.agents,
                    "description": step.description,
                }
                for step in self.steps
            ],
        }


WORKFLOWS: Dict[str, WorkflowDefinition] = {
    "codex_builder": WorkflowDefinition(
        id="codex_builder",
        label="Autonomous Workflow",
        description=(
            "Prompt -> Intent Router -> (Chat | Read-only FS | Run Commands | Research MCP | Jira | Build). "
            "Read-only FS and Run Commands are executed by CLI Agent. "
            "Research branch runs through Research Agent with MCP search/fetch and synthesis. "
            "Jira ticket operations are delegated to Jira REST API Agent. "
            "Build runs through Planner Agent -> SDD Spec Agent -> Code Builder (autonomous CLI execution) -> "
            "Code Review Agent -> Orchestrator Agent summary."
        ),
        steps=[
            WorkflowStep(
                tier=1,
                agents=["Orchestrator Agent"],
                description="Receives user prompt and routes by intent.",
            ),
            WorkflowStep(
                tier=2,
                agents=["Orchestrator Agent"],
                description="Intent router classifies chat/filesystem/commands/research/Jira/build.",
            ),
            WorkflowStep(
                tier=3,
                agents=["CLI Agent", "Research Agent", "Jira REST API Agent"],
                description="Handles read-only filesystem, research intents, explicit command intents, and Jira ticket intents from the router branch.",
            ),
            WorkflowStep(
                tier=4,
                agents=["Planner Agent"],
                description="Build branch collects task and ticket context for spec generation.",
            ),
            WorkflowStep(
                tier=5,
                agents=["SDD Spec Agent"],
                description="Generates requirements.md, design.md, and tasks.md with codebase research.",
            ),
            WorkflowStep(
                tier=6,
                agents=["Code Builder"],
                description="Build branch runs autonomous Codex CLI implementation, build, and test execution.",
            ),
            WorkflowStep(
                tier=7,
                agents=["Code Review Agent"],
                description="Reviews workspace diff and CLI outcomes, then emits pass/fail + fix instructions.",
            ),
            WorkflowStep(
                tier=8,
                agents=["Orchestrator Agent"],
                description="Summarizes completed work, validation state, and next steps.",
            ),
        ],
    )
}


def workflow_list() -> list[dict]:
    return [definition.to_dict() for definition in WORKFLOWS.values()]
