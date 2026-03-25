from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitContentAgentConfig:
    name: str = 'Git Content Agent'
    group: str = 'integrations'
    role: str = 'git_content'
    description: str = (
        'Generates structured branch/PR descriptions from Jira and spec context '
        'for GitHub/GitLab push workflows.'
    )


CONFIG = GitContentAgentConfig()
