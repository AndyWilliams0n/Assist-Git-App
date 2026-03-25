from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JiraApiAgentConfig:
    name: str = "Jira REST API Agent"
    group: str = "integrations"
    role: str = "jira_api"
    description: str = (
        "Handles Jira REST operations including ticket listing, view/create/edit, and Agile board data."
    )


CONFIG = JiraApiAgentConfig()
