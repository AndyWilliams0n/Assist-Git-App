"""Routing / conditional edge functions for the chat graph."""

from __future__ import annotations

from .state import ChatState

_VALID_INTENTS = {
    'chat',
    'research_mcp',
    'jira_api',
    'read_only_fs',
    'run_commands',
    'slack_post',
    'code_build',
}


def route_intent(state: ChatState) -> str:
    intent = state.get('intent', 'chat')

    return intent if intent in _VALID_INTENTS else 'chat'
