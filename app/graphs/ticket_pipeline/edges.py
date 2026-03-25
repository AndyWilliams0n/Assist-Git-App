"""Routing / conditional edge functions for the ticket pipeline graph."""

from __future__ import annotations

from .state import TicketPipelineState


def route_review(state: TicketPipelineState) -> str:
    if state['review_passed']:
        return 'git_handoff'

    if state['attempt'] < state['max_retries']:
        return 'code_build'

    return 'finalise_failed'
