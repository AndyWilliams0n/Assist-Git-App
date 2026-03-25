"""SpecPipelineState TypedDict."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class SpecRequest(TypedDict):
    spec_name: str
    workspace_path: str
    spec_path: str
    ticket_context: dict


class SpecPipelineState(TypedDict):
    batch_id: str
    spec_requests: list[SpecRequest]
    results: Annotated[list[dict], operator.add]
