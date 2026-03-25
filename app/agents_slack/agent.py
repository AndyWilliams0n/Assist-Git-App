from __future__ import annotations

import os
from typing import Any

from app.agent_registry import AgentDefinition, make_agent_id, register_agent
from app.agents_slack.client import SlackClient

SLACK_DEFAULT_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#general")
SLACK_BUILD_CHANNEL = os.getenv("SLACK_BUILD_NOTIFICATIONS_CHANNEL", "")


class SlackAgent:
    def __init__(self) -> None:
        self.client = SlackClient()
        self.agent_id: str | None = None
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        agent_id = make_agent_id("agents", "Slack Agent")
        self.agent_id = agent_id
        register_agent(
            AgentDefinition(
                id=agent_id,
                name="Slack Agent",
                provider=None,
                model=None,
                group="agents",
                role="notifier",
                kind="subagent",
                enabled=self.client.is_configured(),
                dependencies=[],
                source="app/agents_slack/agent.py",
                description="Posts messages to Slack and handles incoming Slack bot events.",
                capabilities=["slack", "notifications", "messaging"],
            )
        )
        self._registered = True

    def is_configured(self) -> bool:
        return self.client.is_configured()

    async def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        return await self.client.post_message(channel, text, thread_ts=thread_ts)

    async def notify_build_complete(
        self,
        summary: str,
        success: bool,
        channel: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        if not self.client.is_configured():
            return
        target_channel = channel or SLACK_BUILD_CHANNEL or SLACK_DEFAULT_CHANNEL
        if not target_channel:
            return
        status_emoji = ":white_check_mark:" if success else ":x:"
        status_label = "Build complete" if success else "Build failed"
        lines = [f"{status_emoji} *{status_label}*"]
        if conversation_id:
            lines.append(f"Conversation: `{conversation_id}`")
        if summary.strip():
            lines.append(summary.strip())
        text = "\n".join(lines)
        try:
            await self.post_message(target_channel, text)
        except Exception as exc:
            print(f"[SlackAgent] notify_build_complete failed: {exc}")
