from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


IntentName = str

_VALID_INTENTS = frozenset({
    'chat',
    'read_only_fs',
    'run_commands',
    'research_mcp',
    'jira_api',
    'code_build',
    'slack_post',
})


@dataclass(frozen=True)
class IntentDecision:
    intent: IntentName
    confidence: float
    reason: str
    source: str
    suggest_mode_switch: bool = field(default=False)
    switch_suggestion: str | None = field(default=None)


# ---------------------------------------------------------------------------
# Keyword patterns — kept as hint extractors and for use by
# _pending_jira_clarification_intent in runtime.py. Not used as routing
# decisions — these are passed to the LLM as supporting context only.
# ---------------------------------------------------------------------------

WORKSPACE_PATTERNS = [
    r'\b(create|add|new|setup)\b.*\bworkspace\b',
    r'\bworkspace\b.*\b(create|add|new|setup|delete|remove|switch|change|activate|select)\b',
    r'\bclone\b.*\b(repo|repository|project)\b',
    r'\b(link|connect|add)\b.*\b(github|gitlab)\b.*\b(repo|repository|project)\b',
    r'\b(list|show|view)\b.*\bworkspaces?\b',
    r'\bswitch workspace\b',
    r'\bactive workspace\b',
]

READ_ONLY_FS_PATTERNS = [
    r'\blist\b.*\bfiles?\b',
    r'\bshow\b.*\bfiles?\b',
    r'\bwhat files\b',
    r'\bfile tree\b',
    r'\bdirectory tree\b',
    r'\bworkspace\b.*\bfiles?\b',
    r'\b(ls|dir)\b',
]

RUN_COMMAND_PATTERNS = [
    r'\brun\b\s+[`\'"]?.+',
    r'\bexecute\b\s+[`\'"]?.+',
    r'\b(delete|remove)\b.*\b(file|files|folder|folders|directory|directories|dir)\b',
    r'\b(rm|mv|cp|mkdir|rmdir|chmod|chown|touch)\b',
    r'\b(npm|pnpm|yarn|pytest|go test|cargo test|uv run)\b',
    r'^\s*make\s+\S+',
]

RESEARCH_PATTERNS = [
    r'\bresearch\b(?!\s+(folder|file|directory|directories|dir|repo|repository|project)\b)',
    r'\b(research|investigate)\b.*\b(topic|question|issue|problem|subject)\b',
    r'\b(research|investigate)\b.*\b(about|on)\b',
    r'\blook up\b',
    r'\bfind sources\b',
    r'\bweb search\b',
    r'\bcitations?\b',
]

JIRA_PATTERNS = [
    r'\bjira\b',
    r'\batlassian\b',
    r'\b[A-Z][A-Z0-9]+-\d+\b',
    r'\bbacklog\b',
    r'\bjql\b',
    r'\b(?:list|show|view|open|create|add|edit|update|delete|remove|attach|comment|transition|move)\b.*\b(?:ticket|tickets|issue|issues)\b',
    r'\b(?:ticket|tickets)\b.*\b(?:jira|backlog|project|board|sprint)\b',
    r'\b(?:rewrite|reword|rephrase|change|update|edit|remove|strip)\b.*\b(?:ticket|tickets|issue|issues|description|summary|acceptance criteria)\b',
    r'\b(?:ticket|tickets|issue|issues|description|summary|acceptance criteria)\b.*\b(?:rewrite|reword|rephrase|change|update|edit|remove|strip)\b',
]

CODE_BUILD_PATTERNS = [
    r'\bbuild\b.*\b(app|api|service|feature|component|project)\b',
    r'\bscaffold\b',
    r'\bimplement\b',
    r'\brefactor\b',
    r'\bfix\b.*\b(ui|frontend|backend|api|app|application|code|bug|issue|error|fail)\b',
    r'\b(review|inspect|audit)\b.*\b(ui|frontend|backend|api|app|application|code)\b',
    r'\b(edit|change|update|align|wire)\b.*\b(ui|frontend|backend|api|app|application|code|form)\b',
    r'\b(edit|change|update|modify)\b.*\b(file|files|codebase|repository|repo|module)\b',
    r'\b(ui|frontend|backend|api)\b.*\b(broken|fail|failing|error|issue|bug)\b',
    r'\bfix\b.*\bbug\b',
    r'\bwrite code\b',
]

SLACK_PATTERNS = [
    r'\bpost\b.*\bslack\b',
    r'\bsend\b.*\bslack\b',
    r'\bslack\b.*\bpost\b',
    r'\bslack\b.*\bmessage\b',
    r'\bmessage\b.*\bslack\b',
    r'\bnotif\w*\b.*\bslack\b',
    r'\bslack\b.*\bnotif\w*\b',
    r'\btell\b.*\bslack\b',
    r'\bslack\b.*\bchannel\b',
]

GIT_PATTERNS = [
    r'\bgit\b',
    r'\bcommit\b.*\b(code|change|file|branch)\b',
    r'\b(push|pull)\b.*\b(branch|remote|origin)\b',
    r'\b(create|open|raise|make)\b.*\b(pr|pull.?request|mr|merge.?request)\b',
    r'\b(pr|pull.?request|mr|merge.?request)\b.*\b(create|open|raise|make)\b',
    r'\b(feature|topic)\s+branch\b',
    r'\b(checkout|switch)\b.*\bbranch\b',
    r'\bgit\s+(status|log|diff|branch|fetch|stash|merge|rebase|cherry-pick)\b',
    r'\b(merge|rebase)\b.*\b(branch|main|master|develop)\b',
    r'\bgithub\b|\bgitlab\b|\bbitbucket\b',
]

EXPLICIT_GIT_OPERATION_PATTERNS = [
    r'\bcommit\b.*\b(code|change|file|branch)\b',
    r'\b(push|pull)\b.*\b(branch|remote|origin)\b',
    r'\b(create|open|raise|make)\b.*\b(pr|pull.?request|mr|merge.?request)\b',
    r'\b(pr|pull.?request|mr|merge.?request)\b.*\b(create|open|raise|make)\b',
    r'\b(feature|topic)\s+branch\b',
    r'\b(checkout|switch)\b.*\bbranch\b',
    r'\bgit\s+(status|log|diff|branch|fetch|stash|merge|rebase|cherry-pick)\b',
    r'\b(merge|rebase)\b.*\b(branch|main|master|develop)\b',
]

# Mode bias prompts injected into the LLM routing call.
_MODE_BIAS: dict[str, str] = {
    'jira': (
        'The user has selected Jira mode. Prefer jira_api for ambiguous messages. '
        'Follow-up messages and conversational replies in an active Jira conversation '
        'should stay as jira_api unless the intent is clearly and unambiguously different '
        '(e.g. the user explicitly asks to build or write code).'
    ),
    'code': (
        'The user has selected Code mode. Prefer code_build for ambiguous messages. '
        'Follow-up messages in an active code conversation should stay as code_build '
        'unless the intent is clearly and unambiguously different.'
    ),
    'code_review': (
        'The user has selected Code Review mode. Prefer read_only_fs for ambiguous messages. '
        'This mode is ask-only: no code writing, editing, or build execution.'
    ),
    'research': (
        'The user has selected Research mode. Prefer research_mcp for ambiguous messages. '
        'Follow-up messages in an active research conversation should stay as research_mcp '
        'unless the intent is clearly and unambiguously different.'
    ),
    'auto': (
        'Auto mode — choose the best intent freely based on the full conversation context. '
        'No preference bias applies.'
    ),
}

_MODE_MISMATCH_EXAMPLES: dict[str, str] = {
    'jira': 'e.g. user explicitly asks to build or write code while in Jira mode',
    'code': 'e.g. user explicitly asks to list Jira tickets while in Code mode',
    'code_review': 'e.g. user explicitly asks to implement, edit, or write code while in Code Review mode',
    'research': 'e.g. user explicitly asks to build or write code while in Research mode',
    'auto': '',
}


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _looks_like_ticket_rewrite_request(text: str) -> bool:
    return _matches_any(text, JIRA_PATTERNS[-2:])


def _looks_like_explicit_git_operation(text: str) -> bool:
    return _matches_any(text, EXPLICIT_GIT_OPERATION_PATTERNS)


def _last_user_message_from_list(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get('role') == 'user':
            return str(msg.get('content') or '')

    return ''


def _format_message_history(messages: list[dict]) -> str:
    lines = []

    for msg in messages:
        role = str(msg.get('role') or 'unknown')
        content = str(msg.get('content') or '').strip()

        if content:
            lines.append(f'[{role}]: {content[:500]}')

    return '\n'.join(lines) if lines else '(no prior messages)'


def _extract_keyword_hints(message: str) -> list[str]:
    hints = []
    lowered = message.lower()

    if _matches_any(lowered, JIRA_PATTERNS):
        hints.append('"ticket"/"jira"/"backlog" keywords detected — may suggest jira_api')

    if _matches_any(lowered, CODE_BUILD_PATTERNS):
        hints.append('code/build keywords detected — may suggest code_build')

    if _matches_any(lowered, RESEARCH_PATTERNS):
        hints.append('research keywords detected — may suggest research_mcp')

    if _matches_any(lowered, SLACK_PATTERNS):
        hints.append('Slack keywords detected — may suggest slack_post')

    if _matches_any(lowered, READ_ONLY_FS_PATTERNS):
        hints.append('filesystem listing keywords detected — may suggest read_only_fs')

    if _matches_any(lowered, RUN_COMMAND_PATTERNS):
        hints.append('command execution keywords detected — may suggest run_commands')

    return hints


def _keyword_fallback(user_message: str) -> IntentDecision:
    """Keyword-based fallback used only when the LLM call fails."""
    message = (user_message or '').strip()
    lowered = message.lower()
    jira_match = _matches_any(lowered, JIRA_PATTERNS)
    explicit_git_match = _looks_like_explicit_git_operation(lowered)
    jira_rewrite_match = _looks_like_ticket_rewrite_request(lowered)

    if jira_match or jira_rewrite_match:
        if explicit_git_match and not jira_rewrite_match:
            jira_match = False
        else:
            return IntentDecision(
                intent='jira_api',
                confidence=0.82,
                reason='Keyword fallback: matched Jira/ticket intent.',
                source='rules',
            )

    if _matches_any(lowered, WORKSPACE_PATTERNS):
        return IntentDecision(
            intent='chat',
            confidence=0.6,
            reason='Keyword fallback: matched workspace wording.',
            source='rules',
        )

    if _matches_any(lowered, GIT_PATTERNS):
        return IntentDecision(
            intent='chat',
            confidence=0.6,
            reason='Keyword fallback: matched git wording.',
            source='rules',
        )

    if _matches_any(lowered, SLACK_PATTERNS):
        return IntentDecision(
            intent='slack_post',
            confidence=0.85,
            reason='Keyword fallback: matched Slack messaging intent.',
            source='rules',
        )

    if _matches_any(lowered, READ_ONLY_FS_PATTERNS):
        return IntentDecision(
            intent='read_only_fs',
            confidence=0.85,
            reason='Keyword fallback: matched filesystem listing intent.',
            source='rules',
        )

    if _matches_any(lowered, RUN_COMMAND_PATTERNS):
        return IntentDecision(
            intent='run_commands',
            confidence=0.8,
            reason='Keyword fallback: matched command execution intent.',
            source='rules',
        )

    if _matches_any(lowered, RESEARCH_PATTERNS):
        return IntentDecision(
            intent='research_mcp',
            confidence=0.82,
            reason='Keyword fallback: matched research intent.',
            source='rules',
        )

    if _matches_any(lowered, CODE_BUILD_PATTERNS):
        return IntentDecision(
            intent='code_build',
            confidence=0.75,
            reason='Keyword fallback: matched code build intent.',
            source='rules',
        )

    return IntentDecision(
        intent='chat',
        confidence=0.5,
        reason='Keyword fallback: no strong intent detected, defaulting to chat.',
        source='rules',
    )


async def resolve_intent(
    self,
    messages: list[dict],
    workflow_mode: str,
) -> IntentDecision:
    """LLM-first intent router with conversation history and mode bias.

    Args:
        self: OrchestratorEngine instance (passed as first positional arg).
        messages: Full conversation message list from ChatState. Last 8 are used.
        workflow_mode: Current UI mode ('auto', 'jira', 'code_review', 'code', 'research').

    Returns:
        IntentDecision with optional soft mode-switch suggestion.
    """
    user_message = _last_user_message_from_list(messages)
    recent_messages = list(messages or [])[-8:]
    history_text = _format_message_history(recent_messages)
    hints = _extract_keyword_hints(user_message)

    mode = str(workflow_mode or 'auto').strip().lower()

    if mode not in _MODE_BIAS:
        mode = 'auto'

    mode_bias_text = _MODE_BIAS[mode]
    mismatch_example = _MODE_MISMATCH_EXAMPLES.get(mode, '')
    hints_text = '\n'.join(f'  - {h}' for h in hints) if hints else '  (none detected)'

    mismatch_guidance = (
        f'Only set suggest_mode_switch=true if the intent is CLEARLY and unambiguously\n'
        f'incompatible with the current mode ({mismatch_example}).\n'
        'Do NOT suggest a switch for follow-up messages, small talk, or vague requests.'
    ) if mode != 'auto' else (
        'suggest_mode_switch should always be false in Auto mode.'
    )

    prompt = (
        'You are an intent router for an AI assistant. '
        'Classify the latest user message into exactly one intent.\n\n'
        f'CURRENT MODE: {mode}\n'
        f'MODE GUIDANCE: {mode_bias_text}\n\n'
        'CONVERSATION HISTORY (oldest first, latest at bottom):\n'
        f'{history_text}\n\n'
        'KEYWORD HINTS (supporting evidence — do not treat as decisions):\n'
        f'{hints_text}\n\n'
        'AVAILABLE INTENTS:\n'
        '  jira_api      — Jira/Atlassian ticket, epic, sprint, backlog operations\n'
        '  code_build    — Write, edit, implement, refactor, or fix code\n'
        '  research_mcp  — Web search, research a topic, find sources, citations\n'
        '  run_commands  — Execute CLI commands or scripts\n'
        '  read_only_fs  — List or read files and folders (no writes)\n'
        '  slack_post    — Post or send a Slack message\n'
        '  chat          — General conversation, questions, no tool execution needed\n\n'
        'INSTRUCTIONS:\n'
        '1. Use the full conversation history to understand follow-up messages.\n'
        '   A short follow-up like "What about now?" continues the prior context.\n'
        '2. Honour the MODE GUIDANCE when routing ambiguous messages.\n'
        f'3. {mismatch_guidance}\n'
        '4. Return valid JSON only — no text outside the JSON object.\n\n'
        'RESPONSE FORMAT:\n'
        '{\n'
        '  "intent": "<intent name>",\n'
        '  "confidence": <0.0-1.0>,\n'
        '  "reason": "<brief one-line explanation>",\n'
        '  "suggest_mode_switch": <true|false>,\n'
        '  "switch_suggestion": "<user-facing tip string, or null>"\n'
        '}'
    )

    try:
        raw = await self._call(self.planner, prompt)
        payload = self._extract_json(raw) or {}
    except Exception:
        return _keyword_fallback(user_message)

    intent = str(payload.get('intent') or '').strip().lower()
    confidence = float(payload.get('confidence') or 0.0)
    reason = str(payload.get('reason') or '').strip() or 'LLM router decision.'
    suggest_switch = bool(payload.get('suggest_mode_switch') or False)
    raw_suggestion = payload.get('switch_suggestion')
    switch_suggestion = str(raw_suggestion).strip() if raw_suggestion else None

    if intent not in _VALID_INTENTS:
        return _keyword_fallback(user_message)

    return IntentDecision(
        intent=intent,
        confidence=max(0.0, min(1.0, confidence)),
        reason=reason,
        source='llm',
        suggest_mode_switch=suggest_switch,
        switch_suggestion=switch_suggestion,
    )


def serialize_intent(decision: IntentDecision) -> str:
    return json.dumps(
        {
            'intent': decision.intent,
            'confidence': decision.confidence,
            'reason': decision.reason,
            'source': decision.source,
            'suggest_mode_switch': decision.suggest_mode_switch,
            'switch_suggestion': decision.switch_suggestion,
        }
    )
