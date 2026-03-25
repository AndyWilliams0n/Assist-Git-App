from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.agent_registry import AgentDefinition, make_agent_id, mark_agent_end, mark_agent_start, register_agent
from app.agents_git_content.config import CONFIG
from app.llm import LLMClient
from app.settings_store import get_agent_model, get_llm_function_settings

_TEMPLATE_VAR_RE = re.compile(r'{{\s*([a-zA-Z0-9_]+)\s*}}')

_DEFAULT_SHARED_PRINCIPLES = '''You are the Git Content Agent for a software delivery team.
Write concise branch/PR descriptions from the completed task context.
Use factual delivery language and avoid unsupported claims.
'''

_DEFAULT_LAYOUT = '''## Brief
- Original request: <source request from Jira ticket or SPEC bundle>

## Changes
- <implementation change>

## Component Dependencies Diagram
```mermaid
flowchart LR
  A["Feature"] --> B["Component"]
```

## Workflow Diagram
```mermaid
flowchart LR
  A["Trigger"] --> B["Action"] --> C["Outcome"]
```

## Test Report
- Coverage (high level): Not available in this run.
- Tests passed count: Not available in this run.

## Risks and Follow-ups
- None noted.
'''

_DEFAULT_PROMPT = '''Generate a branch/PR description markdown document.
Use this exact section structure and order:
{{branch_description_layout}}

Context:
- Workflow type: {{workflow_type}}
- Ticket/spec key: {{ticket_key}}
- Current branch: {{branch_name}}
- Original request: {{original_request}}
- Execution/review summary: {{execution_summary}}
- Changed files:
{{changed_files_block}}

Requirements:
- Return markdown only.
- Keep section headings exactly as shown.
- Include valid Mermaid syntax in both diagram sections.
- If coverage or passed test count is unknown, use: Not available in this run.
'''


class GitContentAgent:
    def __init__(self, registry_mode: str = 'codex') -> None:
        self.registry_mode = registry_mode
        self.agent_id = make_agent_id(registry_mode, CONFIG.name)
        self._registered = False
        self.llm = LLMClient()
        self.templates_dir = Path(__file__).resolve().parent / 'templates'

    def register(self) -> None:
        if self._registered:
            return

        register_agent(
            AgentDefinition(
                id=self.agent_id,
                name=CONFIG.name,
                provider=None,
                model=get_agent_model('git_content'),
                group=CONFIG.group,
                role=CONFIG.role,
                kind='subagent',
                dependencies=[make_agent_id('agents', 'Git Agent')],
                source='app/agents_git_content/runtime.py',
                description=CONFIG.description,
                capabilities=[
                    'git',
                    'branch_description',
                    'pull_request_description',
                    'mermaid_diagrams',
                    'test_summary',
                ],
            )
        )
        self._registered = True

    @staticmethod
    def _normalize_text(value: str, *, fallback: str = 'n/a') -> str:
        text = ' '.join(str(value or '').strip().split())
        return text or fallback

    @staticmethod
    def _render_template(template: str, context: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = str(match.group(1) or '').strip()
            return str(context.get(key) or '').strip()

        return _TEMPLATE_VAR_RE.sub(replace, template)

    def _load_template(self, filename: str, default_text: str) -> str:
        path = self.templates_dir / filename
        try:
            text = path.read_text(encoding='utf-8').strip()
        except Exception:
            text = ''
        return text or default_text.strip()

    @staticmethod
    def _changed_files_block(changed_files: list[str]) -> str:
        if not changed_files:
            return '- Not available in this run.'

        lines = [f'- {item}' for item in changed_files[:60] if str(item or '').strip()]
        return '\n'.join(lines) if lines else '- Not available in this run.'

    @staticmethod
    def _ensure_required_sections(markdown_text: str, fallback: str) -> str:
        required_headings = (
            '## Brief',
            '## Changes',
            '## Component Dependencies Diagram',
            '## Workflow Diagram',
            '## Test Report',
        )
        normalized = str(markdown_text or '').strip()
        if not normalized:
            return fallback
        if all(heading in normalized for heading in required_headings):
            return normalized
        return fallback

    def _fallback_description(self, context: dict[str, Any], layout: str) -> str:
        original_request = self._normalize_text(str(context.get('original_request') or ''), fallback='Not provided.')
        execution_summary = self._normalize_text(str(context.get('execution_summary') or ''), fallback='Not provided.')
        changed_files = context.get('changed_files') if isinstance(context.get('changed_files'), list) else []

        fallback = layout
        fallback = fallback.replace(
            '<source request from Jira ticket or SPEC bundle>',
            original_request,
        )
        fallback = fallback.replace(
            '<implementation change 1>',
            execution_summary,
        )
        fallback = fallback.replace(
            '<implementation change 2>',
            'See changed files list in this branch.',
        )
        fallback = fallback.replace(
            '<known coverage summary or "Not available in this run">',
            'Not available in this run',
        )
        fallback = fallback.replace(
            '<known count or "Not available in this run">',
            'Not available in this run',
        )
        fallback = fallback.replace(
            '<risk, limitation, or follow-up item>',
            'Confirm end-to-end validation in CI before merge.',
        )

        changed_block = self._changed_files_block(changed_files)
        return (fallback + '\n\n### Changed Files\n' + changed_block).strip()

    async def _call_model(self, *, system_prompt: str, user_prompt: str) -> str:
        function_settings = get_llm_function_settings('git_content_generation')
        openai_model = str(function_settings.get('openai_model') or '').strip()
        anthropic_model = str(function_settings.get('anthropic_model') or '').strip()

        if self.llm.openai_api_key and openai_model:
            try:
                return await self.llm.openai_response(system_prompt, user_prompt, model=openai_model)
            except Exception:
                pass

        if self.llm.anthropic_api_key and anthropic_model:
            try:
                return await self.llm.anthropic_response(system_prompt, user_prompt, model=anthropic_model)
            except Exception:
                pass

        return ''

    async def generate_branch_description(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.register()
        mark_agent_start(self.agent_id)

        error_message = ''
        try:
            context = payload if isinstance(payload, dict) else {}
            shared_principles = self._load_template('shared_principles.md', _DEFAULT_SHARED_PRINCIPLES)
            layout = self._load_template('branch_description_layout.md', _DEFAULT_LAYOUT)
            prompt_template = self._load_template('generate_branch_description_prompt.md', _DEFAULT_PROMPT)

            rendered_prompt = self._render_template(
                prompt_template,
                {
                    'branch_description_layout': layout,
                    'workflow_type': self._normalize_text(str(context.get('workflow_type') or ''), fallback='pipeline'),
                    'ticket_key': self._normalize_text(str(context.get('ticket_key') or ''), fallback='n/a'),
                    'branch_name': self._normalize_text(str(context.get('branch_name') or ''), fallback='n/a'),
                    'original_request': self._normalize_text(str(context.get('original_request') or ''), fallback='Not provided.'),
                    'execution_summary': self._normalize_text(str(context.get('execution_summary') or ''), fallback='Not provided.'),
                    'changed_files_block': self._changed_files_block(
                        context.get('changed_files') if isinstance(context.get('changed_files'), list) else []
                    ),
                },
            )

            generated = await self._call_model(system_prompt=shared_principles, user_prompt=rendered_prompt)
            fallback_description = self._fallback_description(context, layout)
            description = self._ensure_required_sections(generated, fallback_description)

            return {
                'success': True,
                'description': description,
                'used_fallback': description == fallback_description,
            }
        except Exception as exc:
            error_message = str(exc).strip() or type(exc).__name__
            return {
                'success': False,
                'description': '',
                'error': error_message,
            }
        finally:
            mark_agent_end(self.agent_id, error=error_message or None)
