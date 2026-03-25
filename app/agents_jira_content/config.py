from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JiraContentAgentConfig:
    name: str = "Jira Content Agent"
    group: str = "integrations"
    role: str = "jira_content"
    description: str = (
        "Generates Jira ticket content for create/edit/comment workflows using software delivery and agile guidance."
    )


CONFIG = JiraContentAgentConfig()
