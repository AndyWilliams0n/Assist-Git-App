"""SpecPipelineGraph definition and compile()."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

from .edges import fan_out_specs
from .nodes import aggregate, generate_sdd, validate_requests
from .state import SpecPipelineState


def build_spec_pipeline_graph(checkpointer: BaseCheckpointSaver):
    """Build and compile the SpecPipelineGraph.

    Args:
        checkpointer: Shared AsyncPostgresSaver instance.

    Returns:
        A compiled LangGraph graph ready to ainvoke().
    """
    g = StateGraph(SpecPipelineState)

    g.add_node('validate_requests', validate_requests)
    g.add_node('generate_sdd', generate_sdd)
    g.add_node('aggregate', aggregate)

    g.add_edge(START, 'validate_requests')
    g.add_conditional_edges('validate_requests', fan_out_specs, ['generate_sdd'])
    g.add_edge('generate_sdd', 'aggregate')
    g.add_edge('aggregate', END)

    return g.compile(checkpointer=checkpointer)
