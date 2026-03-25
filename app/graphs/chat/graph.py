"""ChatGraph definition and compile()."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from app.agents_orchestrator.runtime import OrchestratorEngine

from .edges import route_intent
from .nodes import build_chat_nodes
from .state import ChatState

_INTENT_TO_NODE = {
    'chat': 'chat',
    'research_mcp': 'research',
    'jira_api': 'jira',
    'read_only_fs': 'filesystem',
    'run_commands': 'commands',
    'slack_post': 'slack',
    'code_build': 'build',
}

_ALL_BRANCH_NODES = list(_INTENT_TO_NODE.values())


def build_chat_graph(
    checkpointer: BaseCheckpointSaver,
    engine: OrchestratorEngine,
):
    """Build and compile the ChatGraph.

    Args:
        checkpointer: Shared AsyncPostgresSaver instance.
        engine: OrchestratorEngine instance used by all branch nodes.

    Returns:
        A compiled LangGraph graph ready to ainvoke().
    """
    nodes = build_chat_nodes(engine)

    g = StateGraph(ChatState)

    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, 'router')

    g.add_conditional_edges('router', route_intent, _INTENT_TO_NODE)

    for node in _ALL_BRANCH_NODES:
        g.add_edge(node, END)

    return g.compile(checkpointer=checkpointer)
