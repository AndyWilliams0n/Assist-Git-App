"""Fan-out edge functions for the spec pipeline graph."""

from __future__ import annotations

from langgraph.types import Send

from .state import SpecPipelineState


def fan_out_specs(state: SpecPipelineState) -> list[Send]:
    return [
        Send('generate_sdd', {'spec': req})
        for req in state['spec_requests']
    ]
