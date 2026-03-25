"""TicketPipelineState TypedDict."""

from __future__ import annotations

from typing import TypedDict


class TicketPipelineState(TypedDict):
    task_id: str
    jira_key: str
    pipeline_id: str
    task_source: str
    task_relation: str
    starting_git_branch_override: str
    ticket_context: dict
    workspace_path: str
    plan: str
    sdd_bundle_path: str
    build_result: dict
    review_passed: bool
    review_reason: str
    git_result: dict
    attempt: int
    max_retries: int
    status: str
    failure_reason: str | None
    run_id: str
