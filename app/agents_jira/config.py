from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JiraAgentConfig:
    name: str = "Jira MCP Agent"
    group: str = "integrations"
    role: str = "jira_mcp"
    description: str = "Handles Jira ticket listing, viewing, creation, and updates through configured MCP tools."


CONFIG = JiraAgentConfig()
