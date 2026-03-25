"""Node functions for the spec pipeline graph."""

from __future__ import annotations

import logging

from app.agents_sdd_spec.runtime import run_sdd_spec_agent
from app.pipeline_store import add_pipeline_log
from app.ticket_context import TicketContext

from .state import SpecPipelineState, SpecRequest

logger = logging.getLogger(__name__)

_REQUIRED_SPEC_FIELDS = ('spec_name', 'workspace_path', 'spec_path')


def _is_valid_spec_request(req: object) -> bool:
    if not isinstance(req, dict):
        return False

    return all(bool(str(req.get(field) or '').strip()) for field in _REQUIRED_SPEC_FIELDS)


def _build_ticket_context(raw: object) -> TicketContext | None:
    if not isinstance(raw, dict) or not raw:
        return None

    try:
        return TicketContext.from_dict(raw)
    except Exception:
        return None


async def validate_requests(state: SpecPipelineState) -> dict:
    valid = [req for req in state['spec_requests'] if _is_valid_spec_request(req)]
    skipped = len(state['spec_requests']) - len(valid)
    batch_id = state['batch_id']

    add_pipeline_log(
        level='info',
        message=f'Spec pipeline batch {batch_id}: starting — {len(valid)} spec(s) queued.',
    )

    if skipped > 0:
        logger.warning('SpecPipeline: skipped %d invalid spec requests', skipped)
        add_pipeline_log(
            level='warning',
            message=f'Spec pipeline batch {batch_id}: skipped {skipped} invalid request(s).',
        )

    return {'spec_requests': valid}


async def generate_sdd(state: dict) -> dict:
    spec: SpecRequest = state.get('spec', {})
    spec_name = str(spec.get('spec_name') or '')
    workspace_path = str(spec.get('workspace_path') or '')
    spec_path = str(spec.get('spec_path') or '')
    raw_ticket_context = spec.get('ticket_context') or {}

    ticket_context = _build_ticket_context(raw_ticket_context)

    task_prompt = (
        f'Generate a complete SDD bundle for: {spec_name}.\n'
        'Follow the standard requirements / design / tasks structure.'
    )

    add_pipeline_log(
        level='info',
        message=f'[{spec_name}] SDD generation started.',
    )

    try:
        result = await run_sdd_spec_agent(
            task_prompt=task_prompt,
            ticket_context=ticket_context,
            workspace_path=workspace_path,
            output_dir=spec_path,
        )

        status = result.get('status', 'unknown')
        error = result.get('error', '')

        if status == 'success':
            add_pipeline_log(
                level='info',
                message=f'[{spec_name}] SDD generation succeeded.',
            )
        else:
            add_pipeline_log(
                level='error',
                message=f'[{spec_name}] SDD generation failed: {error}' if error else f'[{spec_name}] SDD generation failed.',
            )

        return {
            'results': [
                {
                    'spec_name': spec_name,
                    'status': status,
                    'spec_path': spec_path,
                    'error': error,
                }
            ]
        }
    except Exception as exc:
        logger.error('generate_sdd failed for %s: %s', spec_name, exc)
        add_pipeline_log(
            level='error',
            message=f'[{spec_name}] SDD generation failed: {exc}',
        )

        return {
            'results': [
                {
                    'spec_name': spec_name,
                    'status': 'failed',
                    'spec_path': spec_path,
                    'error': str(exc),
                }
            ]
        }


async def aggregate(state: SpecPipelineState) -> dict:
    results = state.get('results') or []
    batch_id = state.get('batch_id', '')
    total = len(results)
    succeeded = sum(1 for r in results if str(r.get('status') or '') == 'success')
    failed = total - succeeded

    summary = (
        f'Spec pipeline batch {batch_id} complete: '
        f'{succeeded}/{total} succeeded, {failed} failed.'
    )
    logger.info(summary)
    add_pipeline_log(level='info', message=summary)

    return {}
