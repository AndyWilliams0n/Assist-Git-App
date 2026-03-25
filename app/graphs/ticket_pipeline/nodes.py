"""Node functions for the ticket pipeline graph.

All node functions are built as closures over a PipelineEngine instance so that they
can call existing pipeline agent methods without circular imports.
Call build_ticket_pipeline_nodes(engine) to get a dict of ready-to-use async functions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.agents_pipeline.runtime import PipelineEngine

from app.agents_code_review.runtime import run_code_review_with_codex
from app.agents_pipeline.config import CODEX_TIMEOUT_SECONDS
from app.db import SPEC_TASK_STATUS_COMPLETE, SPEC_TASK_STATUS_FAILED
from app.pipeline_store import (
    PIPELINE_BYPASS_SOURCE_AUTO_FAILURE,
    PIPELINE_RUN_STATUS_COMPLETE,
    PIPELINE_RUN_STATUS_FAILED,
    PIPELINE_STATUS_COMPLETE,
    PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
    PIPELINE_TASK_SOURCE_SPEC,
    PIPELINE_WORKFLOW,
    add_pipeline_git_handoff,
    add_pipeline_log,
    finalize_pipeline_run,
    get_pipeline_task,
    get_shared_max_retries,
    list_pipeline_task_dependents,
    set_pipeline_task_result,
    update_pipeline_run_progress,
)
from app.settings_store import get_agent_model

from .state import TicketPipelineState

logger = logging.getLogger(__name__)


def build_ticket_pipeline_nodes(engine: PipelineEngine) -> dict[str, Callable]:
    """Return a dict of node-name → async node function, all closed over engine."""

    async def fetch_context(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        workspace_path = state['workspace_path']
        run_id = state['run_id']
        task_source = state.get('task_source') or 'jira'
        max_retries = get_shared_max_retries()

        update_pipeline_run_progress(
            run_id,
            attempt_count=0,
            max_retries=max_retries,
            attempts_failed=0,
            attempts_completed=0,
            current_activity='Loading spec context.' if task_source == PIPELINE_TASK_SOURCE_SPEC else 'Fetching ticket context from Jira.',
        )

        if task_source == PIPELINE_TASK_SOURCE_SPEC:
            add_pipeline_log(
                level='info',
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=f'fetch_context: loading spec details for {jira_key} (no Jira fetch).',
            )
            task = get_pipeline_task(task_id)
            details = engine._build_spec_task_details(task, jira_key)

            spec = details.get('spec') or {}
            spec_path = str(spec.get('spec_path') or spec.get('workspace_path') or workspace_path).strip()
            if spec_path:
                images_dir = (Path(spec_path).expanduser().resolve() / 'images')
                if images_dir.exists() and any(images_dir.iterdir()):
                    try:
                        workspace_root = Path(workspace_path).expanduser().resolve()
                        details['attachment_root_relative'] = str(images_dir.relative_to(workspace_root))
                    except ValueError:
                        details['attachment_root_relative'] = str(images_dir)
        else:
            add_pipeline_log(
                level='info',
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=f'fetch_context: loading Jira details for {jira_key}.',
            )
            details = await engine._fetch_jira_task_details(jira_key)
            attachment_download = await engine._materialize_jira_attachments(
                workspace_path=workspace_path,
                jira_key=jira_key,
                details=details,
            )

            if attachment_download.get('warnings'):
                existing = details.get('warnings') if isinstance(details.get('warnings'), list) else []
                details['warnings'] = [*existing, *attachment_download['warnings']]

        await engine._attach_assist_brain_context(
            details=details,
            jira_key=jira_key,
            task_source=task_source,
            workspace_path=workspace_path,
            task_id=task_id,
            run_id=run_id,
        )

        return {
            'ticket_context': details,
            'max_retries': max_retries,
        }

    async def sdd_spec(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        run_id = state['run_id']
        workspace_path = state['workspace_path']
        task_source = state.get('task_source') or 'jira'
        task_relation = state.get('task_relation') or 'task'
        starting_git_branch_override = state.get('starting_git_branch_override') or ''
        details = state.get('ticket_context') or {}
        version = int(state.get('pipeline_id', '1') or 1)
        is_spec = task_source == PIPELINE_TASK_SOURCE_SPEC
        workflow_key = 'pipeline_spec' if is_spec else 'pipeline'
        context_type = 'pipeline_spec' if is_spec else 'pipeline'
        ticket_summary = str(details.get('ticket', {}).get('summary') if isinstance(details.get('ticket'), dict) else '') or jira_key

        # Run planning hook for all task types — this creates the working branch
        planning_git_hook = await engine._run_git_hook(
            stage_id='planning',
            workspace_path=workspace_path,
            context={
                'description': ticket_summary,
                'ticket': jira_key,
                'summary': ticket_summary,
                'type': context_type,
            },
            workflow_key=workflow_key,
            starting_git_branch_override=starting_git_branch_override,
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            task_relation=task_relation,
        )
        engine._ensure_git_hook_succeeded(planning_git_hook)

        if is_spec:
            add_pipeline_log(
                level='info',
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=f'sdd_spec: loading existing SDD bundle for spec {jira_key}.',
            )
            update_pipeline_run_progress(
                run_id,
                attempt_count=0,
                max_retries=state.get('max_retries', 1),
                attempts_failed=0,
                attempts_completed=0,
                current_activity='Loading SDD specification bundle.',
            )
            task = get_pipeline_task(task_id)
            bundle = engine._resolve_existing_spec_bundle(
                task=task,
                workspace_path=workspace_path,
                spec_key=jira_key,
            )
            return {'sdd_bundle_path': json.dumps(bundle)}

        add_pipeline_log(
            level='info',
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=f'sdd_spec: generating SDD bundle for {jira_key}.',
        )
        update_pipeline_run_progress(
            run_id,
            attempt_count=0,
            max_retries=state.get('max_retries', 1),
            attempts_failed=0,
            attempts_completed=0,
            current_activity='Generating SDD specification bundle.',
        )

        bundle = await engine._delegate_to_sdd_spec_agent(
            jira_key=jira_key,
            version=version,
            workspace_path=workspace_path,
            details=details,
        )

        return {'sdd_bundle_path': json.dumps(bundle)}

    async def code_build(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        run_id = state['run_id']
        workspace_path = state['workspace_path']
        task_source = state.get('task_source') or 'jira'
        task_relation = state.get('task_relation') or 'task'
        starting_git_branch_override = state.get('starting_git_branch_override') or ''
        details = state.get('ticket_context') or {}
        attempt = state.get('attempt', 0) + 1
        max_retries = state.get('max_retries', 1)
        is_spec = task_source == PIPELINE_TASK_SOURCE_SPEC
        workflow_key = 'pipeline_spec' if is_spec else 'pipeline'
        context_type = 'pipeline_spec' if is_spec else 'pipeline'
        ticket_summary = str(details.get('ticket', {}).get('summary') if isinstance(details.get('ticket'), dict) else '') or jira_key

        raw_bundle = state.get('sdd_bundle_path') or '{}'
        try:
            sdd_bundle = json.loads(raw_bundle)
        except Exception:
            sdd_bundle = {}

        add_pipeline_log(
            level='info',
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=f'code_build: attempt {attempt}/{max_retries} for {jira_key}.',
        )
        update_pipeline_run_progress(
            run_id,
            attempt_count=attempt,
            max_retries=max_retries,
            attempts_failed=attempt - 1,
            attempts_completed=0,
            current_activity=f'Attempt {attempt}/{max_retries}: building code.',
        )

        failure_reason = str(state.get('failure_reason') or '')
        repair_feedback = (
            f'Previous failure to address:\n{failure_reason}'
            if failure_reason
            else ''
        )

        result = await engine._run_codex_builder(
            workspace_path=workspace_path,
            task_key=jira_key,
            task_source=task_source,
            sdd_bundle=sdd_bundle,
            details=details,
            repair_feedback=repair_feedback,
            previous_failure_reason=failure_reason,
            attempt_number=attempt,
            max_attempts=max_retries,
        )

        build_git_hook = await engine._run_git_hook(
            stage_id='build',
            workspace_path=workspace_path,
            context={
                'description': ticket_summary,
                'ticket': jira_key,
                'summary': str(result.get('summary') or ''),
                'type': context_type,
            },
            workflow_key=workflow_key,
            starting_git_branch_override=starting_git_branch_override,
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            task_relation=task_relation,
        )
        engine._ensure_git_hook_succeeded(build_git_hook)

        return {
            'build_result': result,
            'attempt': attempt,
            'failure_reason': str(result.get('error') or ''),
        }

    async def code_review(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        run_id = state['run_id']
        workspace_path = state['workspace_path']
        build_result = state.get('build_result') or {}

        raw_bundle = state.get('sdd_bundle_path') or '{}'
        try:
            sdd_bundle = json.loads(raw_bundle)
        except Exception:
            sdd_bundle = {}

        add_pipeline_log(
            level='info',
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=f'code_review: reviewing build output for {jira_key}.',
        )
        update_pipeline_run_progress(
            run_id,
            attempt_count=state.get('attempt', 1),
            max_retries=state.get('max_retries', 1),
            attempts_failed=state.get('attempt', 1) - 1,
            attempts_completed=0,
            current_activity='Running code review.',
        )

        from app.settings_store import get_agent_bypass_settings
        bypass = get_agent_bypass_settings()

        if bool(bypass.get('code_review')):
            return {
                'review_passed': True,
                'review_reason': 'Code review bypassed.',
            }

        add_pipeline_log(
            level='info',
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=f'code_review: running Codex review for {jira_key} (timeout {CODEX_TIMEOUT_SECONDS}s).',
        )

        try:
            review = await run_code_review_with_codex(
                workspace_path=workspace_path,
                spec_paths=sdd_bundle,
                build_output=str(build_result.get('summary') or build_result.get('error') or ''),
                model=get_agent_model('code_review'),
                timeout_seconds=CODEX_TIMEOUT_SECONDS,
            )
            passed = bool(review.get('passed', False))
            reason = str(review.get('reason') or review.get('summary') or '')
        except Exception as exc:
            logger.error('code_review failed for %s: %s', jira_key, exc)
            passed = False
            reason = str(exc)

        return {
            'review_passed': passed,
            'review_reason': reason,
        }

    async def git_handoff(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        run_id = state['run_id']
        workspace_path = state['workspace_path']
        task_source = state.get('task_source') or 'jira'
        task_relation = state.get('task_relation') or 'task'
        starting_git_branch_override = state.get('starting_git_branch_override') or ''
        is_spec = task_source == PIPELINE_TASK_SOURCE_SPEC
        workflow_key = 'pipeline_spec' if is_spec else 'pipeline'
        context_type = 'pipeline_spec' if is_spec else 'pipeline'
        build_result = state.get('build_result') or {}
        details = state.get('ticket_context') or {}
        ticket_summary = str(details.get('ticket', {}).get('summary') if isinstance(details.get('ticket'), dict) else '') or jira_key
        review_summary = str(state.get('review_reason') or build_result.get('summary') or '')

        add_pipeline_log(
            level='info',
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=f'git_handoff: running git review hook for {jira_key}.',
        )

        git_result = await engine._run_git_hook(
            stage_id='review',
            workspace_path=workspace_path,
            context={
                'description': ticket_summary,
                'ticket': jira_key,
                'summary': review_summary,
                'type': context_type,
            },
            workflow_key=workflow_key,
            starting_git_branch_override=starting_git_branch_override,
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            task_relation=task_relation,
        )

        if bool(git_result.get('ok')):
            add_pipeline_git_handoff(
                run_id=run_id,
                task_id=task_id,
                jira_key=jira_key,
                strategy=str(git_result.get('action') or 'push'),
                reason=str(git_result.get('message') or git_result.get('reason') or 'git review hook completed'),
            )

        return {'git_result': git_result}

    async def finalise_success(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        run_id = state['run_id']
        workspace_path = state['workspace_path']
        task_source = state.get('task_source') or 'jira'
        task_relation = state.get('task_relation') or 'task'
        starting_git_branch_override = state.get('starting_git_branch_override') or ''
        is_spec = task_source == PIPELINE_TASK_SOURCE_SPEC
        workflow_key = 'pipeline_spec' if is_spec else 'pipeline'
        context_type = 'pipeline_spec' if is_spec else 'pipeline'
        build_result = state.get('build_result') or {}
        details = state.get('ticket_context') or {}
        ticket_summary = str(details.get('ticket', {}).get('summary') if isinstance(details.get('ticket'), dict) else '') or jira_key
        attempt = state.get('attempt', 1)
        max_retries = state.get('max_retries', 1)

        raw_bundle = state.get('sdd_bundle_path') or '{}'
        try:
            sdd_bundle = json.loads(raw_bundle)
        except Exception:
            sdd_bundle = {}

        # Run complete stage hook — executes whatever action is configured in the git actions UI
        await engine._run_git_hook(
            stage_id='complete',
            workspace_path=workspace_path,
            context={
                'description': ticket_summary,
                'ticket': jira_key,
                'summary': str(build_result.get('summary') or ''),
                'type': context_type,
            },
            workflow_key=workflow_key,
            starting_git_branch_override=starting_git_branch_override,
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            task_relation=task_relation,
        )

        finalize_pipeline_run(
            run_id,
            status=PIPELINE_RUN_STATUS_COMPLETE,
            attempt_count=attempt,
            max_retries=max_retries,
            attempts_failed=attempt - 1,
            attempts_completed=1,
            current_activity='Pipeline completed successfully.',
            brief_path=str(sdd_bundle.get('requirements_path') or ''),
            spec_path=str(sdd_bundle.get('design_path') or ''),
            task_path=str(sdd_bundle.get('tasks_path') or ''),
            codex_status=str(build_result.get('status') or 'success'),
            codex_summary=str(build_result.get('summary') or ''),
        )

        updated_task = set_pipeline_task_result(
            task_id,
            status=PIPELINE_STATUS_COMPLETE,
            failure_reason=None,
        )

        for dependent_id in list_pipeline_task_dependents(task_id):
            engine._refresh_dependency_state_for_task(dependent_id)

        engine._set_spec_task_status_for_pipeline_task(
            task=updated_task if isinstance(updated_task, dict) else (get_pipeline_task(task_id) or {}),
            status=SPEC_TASK_STATUS_COMPLETE,
            context='run:result',
            sync_backlog=True,
        )

        if not is_spec and isinstance(updated_task, dict):
            await engine._move_completed_jira_ticket_to_selected_column(
                task=updated_task,
                jira_key=jira_key,
                task_id=task_id,
                run_id=run_id,
            )

        await engine._notify_pipeline_build_complete(
            jira_key=jira_key,
            workspace_path=workspace_path,
            workflow=PIPELINE_WORKFLOW,
            success=True,
            attempt_count=attempt,
            max_retries=max_retries,
            attempts_running=0,
            attempts_completed=1,
            attempts_failed=attempt - 1,
            codex_status=str(build_result.get('status') or 'success'),
            codex_summary=str(build_result.get('summary') or ''),
        )

        await engine._capture_pipeline_outcome_memory(
            jira_key=jira_key,
            task_source=task_source,
            workspace_path=workspace_path,
            workflow=PIPELINE_WORKFLOW,
            success=True,
            version=int(state.get('pipeline_id', '1') or 1),
            attempt_count=int(attempt),
            max_retries=int(max_retries),
            codex_status=str(build_result.get('status') or 'success'),
            codex_summary=str(build_result.get('summary') or ''),
            failure_reason='',
            task_id=task_id,
            run_id=run_id,
        )

        return {'status': 'complete'}

    async def finalise_failed(state: TicketPipelineState) -> dict:
        task_id = state['task_id']
        jira_key = state['jira_key']
        run_id = state['run_id']
        workspace_path = state['workspace_path']
        build_result = state.get('build_result') or {}
        failure_reason = str(state.get('failure_reason') or state.get('review_reason') or 'Unknown failure.')
        attempt = state.get('attempt', 1)
        max_retries = state.get('max_retries', 1)

        finalize_pipeline_run(
            run_id,
            status=PIPELINE_RUN_STATUS_FAILED,
            attempt_count=attempt,
            max_retries=max_retries,
            attempts_failed=attempt,
            attempts_completed=0,
            current_activity='Pipeline failed after all retry attempts.',
            failure_reason=failure_reason,
        )

        updated_task = engine._recover_task_to_queue(
            task=get_pipeline_task(task_id) or {"id": task_id, "jira_key": jira_key},
            run_id=run_id,
            reason=failure_reason,
            failure_code="max_retries_exhausted",
            bypass_source=PIPELINE_BYPASS_SOURCE_AUTO_FAILURE,
            bypassed_by="system",
            execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
            create_handoff=False,
            apply_shared_branch_block=False,
        )

        for dependent_id in list_pipeline_task_dependents(task_id):
            engine._refresh_dependency_state_for_task(dependent_id)

        engine._set_spec_task_status_for_pipeline_task(
            task=updated_task if isinstance(updated_task, dict) else (get_pipeline_task(task_id) or {}),
            status=SPEC_TASK_STATUS_FAILED,
            context='run:result',
            sync_backlog=True,
        )

        await engine._notify_pipeline_build_complete(
            jira_key=jira_key,
            workspace_path=workspace_path,
            workflow=PIPELINE_WORKFLOW,
            success=False,
            attempt_count=attempt,
            max_retries=max_retries,
            attempts_running=0,
            attempts_completed=0,
            attempts_failed=attempt,
            codex_status=str(build_result.get('status') or 'failed'),
            codex_summary=str(build_result.get('error') or ''),
            failure_reason=failure_reason,
        )

        await engine._capture_pipeline_outcome_memory(
            jira_key=jira_key,
            task_source=str(state.get('task_source') or 'jira'),
            workspace_path=workspace_path,
            workflow=PIPELINE_WORKFLOW,
            success=False,
            version=int(state.get('pipeline_id', '1') or 1),
            attempt_count=int(attempt),
            max_retries=int(max_retries),
            codex_status=str(build_result.get('status') or 'failed'),
            codex_summary=str(build_result.get('error') or ''),
            failure_reason=failure_reason,
            task_id=task_id,
            run_id=run_id,
        )

        return {'status': 'failed', 'failure_reason': failure_reason}

    return {
        'fetch_context': fetch_context,
        'sdd_spec': sdd_spec,
        'code_build': code_build,
        'code_review': code_review,
        'git_handoff': git_handoff,
        'finalise_success': finalise_success,
        'finalise_failed': finalise_failed,
    }
