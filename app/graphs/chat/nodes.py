"""Node functions for the chat graph.

All node functions are built as closures over an OrchestratorEngine instance
so that they can delegate to existing agent runtimes without circular imports.
Call build_chat_nodes(engine) to get a dict of ready-to-use async node functions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.agents_orchestrator.runtime import OrchestratorEngine

from app.db import add_message, add_orchestrator_event, conversation_messages
from app.workspace import WorkspaceManager

from .state import ChatState

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_user_message(state: ChatState) -> str:
    messages = state.get('messages') or []

    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get('role') == 'user':
            return str(msg.get('content') or '')

    return ''


def _effective_user_message(state: ChatState) -> str:
    user_message = _last_user_message(state)
    attachment_context = str(state.get('attachment_context') or '').strip()

    if attachment_context:
        return f'{user_message.strip()}\n\n{attachment_context}'

    return user_message


def _build_workspace(path: str | None) -> WorkspaceManager:
    if path and str(path).strip():
        return WorkspaceManager(path, mode='read_write')

    return WorkspaceManager(mode='read_write')


def _build_secondary_workspace(path: str | None, primary: WorkspaceManager) -> WorkspaceManager | None:
    if not path or not str(path).strip():
        return None

    resolved = str(path).strip()

    if Path(resolved).resolve() == primary.root:
        return None

    secondary = WorkspaceManager(resolved, mode='read_only')

    if not secondary.root.exists() or not secondary.root.is_dir():
        return None

    return secondary


def build_chat_nodes(engine: OrchestratorEngine) -> dict[str, Callable]:
    """Return a dict of node-name → async node function, all closed over engine."""

    from app import intent_router as router
    from app.agents_orchestrator.runtime import (
        _enforce_workflow_mode,
        _normalize_orchestrator_intent,
        _normalize_workflow_mode,
        _pending_jira_clarification_intent,
    )

    async def router_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _last_user_message(state)
        workspace_path = str(state.get('workspace_path') or '')
        workflow_mode = str(state.get('workflow_mode') or 'auto')

        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type='turn_started',
            content='',
        )

        recent_messages = list(state.get('messages') or [])[-8:]

        workspace_root = Path(workspace_path) if workspace_path else Path.cwd()
        selected_workflow_mode = _normalize_workflow_mode(workflow_mode)

        pending_jira_intent = _pending_jira_clarification_intent(
            workspace_root, conversation_id, user_message
        )
        resolved_intent = pending_jira_intent or await router.resolve_intent(
            engine, recent_messages, selected_workflow_mode
        )
        normalized_intent = _normalize_orchestrator_intent(resolved_intent)
        enforced_intent, workflow_mode_reply = _enforce_workflow_mode(
            selected_workflow_mode, normalized_intent
        )
        final_intent = enforced_intent or normalized_intent

        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type='workflow_selected',
            content=router.serialize_intent(final_intent),
        )

        # Emit a non-blocking mode switch suggestion when the LLM detects a
        # clear mismatch between the active mode and the request intent.
        # The turn still routes normally — the user sees a tip, not a dead end.
        if normalized_intent.suggest_mode_switch and normalized_intent.switch_suggestion:
            suggestion = normalized_intent.switch_suggestion

            add_message(
                conversation_id,
                role='assistant',
                agent=engine.orchestrator.name,
                content=suggestion,
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=engine.orchestrator.name,
                event_type='assistant_message',
                content=suggestion,
            )

        if workflow_mode_reply:
            add_message(
                conversation_id,
                role='assistant',
                agent=engine.orchestrator.name,
                content=workflow_mode_reply,
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=engine.orchestrator.name,
                event_type='assistant_message',
                content=workflow_mode_reply,
            )
            return {
                'intent': 'chat',
                'intent_confidence': 0.99,
                'intent_source': 'workflow_mode_block',
                'result': workflow_mode_reply,
            }

        return {
            'intent': final_intent.intent,
            'intent_confidence': final_intent.confidence,
            'intent_source': final_intent.source,
        }

    async def chat_node(state: ChatState) -> dict:
        if state.get('result'):
            return {}

        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        memory = conversation_messages(conversation_id)

        turn = await engine._run_general_workflow(
            conversation_id, user_message, memory
        )

        return {'result': str(turn.get('reply') or '')}

    async def research_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        workspace_path = str(state.get('workspace_path') or '')
        memory = conversation_messages(conversation_id)

        ack = 'Researching in the background\u2026 I\u2019ll post results here when done.'
        add_message(
            conversation_id,
            role='assistant',
            agent=engine.orchestrator.name,
            content=ack,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type='assistant_message',
            content=ack,
        )

        task = asyncio.create_task(
            _research_background(
                engine=engine,
                conversation_id=conversation_id,
                user_message=user_message,
                memory=memory,
                workspace_path=workspace_path,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return {
            'result': ack,
            'research_task_id': str(id(task)),
        }

    async def jira_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        workspace_path = str(state.get('workspace_path') or '')
        selected_ticket_keys = list(state.get('selected_ticket_keys') or [])
        memory = conversation_messages(conversation_id)
        workspace = _build_workspace(workspace_path)

        turn = await engine._run_jira_workflow(
            conversation_id,
            user_message,
            memory,
            workspace,
            selected_ticket_keys=selected_ticket_keys,
        )

        return {'result': str(turn.get('reply') or '')}

    async def filesystem_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        workspace_path = str(state.get('workspace_path') or '')
        selected_workflow_mode = _normalize_workflow_mode(str(state.get('workflow_mode') or 'auto'))
        workspace = WorkspaceManager(workspace_path, mode='read_only') if workspace_path else WorkspaceManager(mode='read_only')

        if selected_workflow_mode == 'code_review':
            turn = await engine._run_codex_review_workflow(
                conversation_id, user_message, workspace
            )
        else:
            turn = await engine._run_read_only_fs_workflow(
                conversation_id, user_message, workspace
            )

        return {'result': str(turn.get('reply') or '')}

    async def commands_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        workspace_path = str(state.get('workspace_path') or '')
        workspace = _build_workspace(workspace_path)

        turn = await engine._run_run_workflow(
            conversation_id, user_message, workspace
        )

        return {'result': str(turn.get('reply') or '')}

    async def slack_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        memory = conversation_messages(conversation_id)

        turn = await engine._run_slack_workflow(
            conversation_id, user_message, memory
        )

        return {'result': str(turn.get('reply') or '')}

    async def build_node(state: ChatState) -> dict:
        conversation_id = state['conversation_id']
        user_message = _effective_user_message(state)
        workspace_path = str(state.get('workspace_path') or '')
        secondary_workspace_path = str(state.get('secondary_workspace_path') or '')
        selected_ticket_contexts = list(state.get('selected_ticket_contexts') or [])
        memory = conversation_messages(conversation_id)
        workspace = _build_workspace(workspace_path)
        secondary_workspace = _build_secondary_workspace(secondary_workspace_path, workspace)

        turn = await engine._run_codex_build_workflow(
            conversation_id,
            user_message,
            memory,
            workspace,
            secondary_workspace=secondary_workspace,
            selected_ticket_contexts=selected_ticket_contexts,
        )

        return {'result': str(turn.get('reply') or '')}

    return {
        'router': router_node,
        'chat': chat_node,
        'research': research_node,
        'jira': jira_node,
        'filesystem': filesystem_node,
        'commands': commands_node,
        'slack': slack_node,
        'build': build_node,
    }


async def _research_background(
    *,
    engine: OrchestratorEngine,
    conversation_id: str,
    user_message: str,
    memory: list[dict],
    workspace_path: str,
) -> None:
    workspace = _build_workspace(workspace_path)

    try:
        await engine._run_research_workflow(
            conversation_id, user_message, memory, workspace
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent='Research Agent',
            event_type='research_complete',
            content=f'{{"type": "research_complete", "conversation_id": "{conversation_id}", "timestamp": "{_utc_now()}"}}',
        )
    except Exception as exc:
        logger.error('Background research failed: %s', exc)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent='Research Agent',
            event_type='research_error',
            content=str(exc),
        )
