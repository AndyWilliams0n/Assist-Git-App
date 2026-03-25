"""TicketPipelineGraph definition and compile()."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from app.agents_pipeline.runtime import PipelineEngine

from .edges import route_review
from .nodes import build_ticket_pipeline_nodes
from .state import TicketPipelineState


def build_ticket_pipeline_graph(
    checkpointer: BaseCheckpointSaver,
    engine: PipelineEngine,
):
    """Build and compile the TicketPipelineGraph.

    Args:
        checkpointer: Shared AsyncPostgresSaver instance.
        engine: PipelineEngine instance used by all pipeline nodes.

    Returns:
        A compiled LangGraph graph ready to ainvoke().
    """
    nodes = build_ticket_pipeline_nodes(engine)

    g = StateGraph(TicketPipelineState)

    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, 'fetch_context')
    g.add_edge('fetch_context', 'sdd_spec')
    g.add_edge('sdd_spec', 'code_build')
    g.add_edge('code_build', 'code_review')

    g.add_conditional_edges(
        'code_review',
        route_review,
        {
            'git_handoff': 'git_handoff',
            'code_build': 'code_build',
            'finalise_failed': 'finalise_failed',
        },
    )

    g.add_edge('git_handoff', 'finalise_success')
    g.add_edge('finalise_success', END)
    g.add_edge('finalise_failed', END)

    return g.compile(checkpointer=checkpointer)
