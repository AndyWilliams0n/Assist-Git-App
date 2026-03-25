from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.agent_registry import AgentDefinition, make_agent_id, mark_agent_end, mark_agent_start, register_agent
from app.agents_jira_content.config import CONFIG
from app.llm import LLMClient
from app.settings_store import get_agent_model, get_llm_function_settings

_TEMPLATE_VAR_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
_SUMMARY_LINE_RE = re.compile(r"^SUMMARY:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DESCRIPTION_MARKER_RE = re.compile(r"^DESCRIPTION:\s*$", re.IGNORECASE | re.MULTILINE)
_COMMENT_MARKER_RE = re.compile(r"^COMMENT:\s*$", re.IGNORECASE | re.MULTILINE)
_MAX_STRUCTURE_ATTEMPTS = 3
CREATE_DESCRIPTION_SECTION_TITLES = (
    "User Story",
    "Requirements",
    "Acceptance Criteria",
    "Agent Context",
    "Agent Prompt",
)
EDIT_DESCRIPTION_SECTION_TITLES = CREATE_DESCRIPTION_SECTION_TITLES
ATTACHMENT_CONTEXT_MARKER = "Attachment context for this conversation:"
_ATTACHMENT_FILENAME_RE = re.compile(r".+\.(?:png|jpe?g|gif|webp|svg|pdf|fig|sketch|xd)$", re.IGNORECASE)

_DEFAULT_SHARED_PRINCIPLES = """You are the Jira Content Agent for a software delivery team.
Write like a strong product manager / delivery lead preparing implementation-ready Jira tickets.
Priorities:
- Ground every output in the user's actual request and any parent ticket context.
- Use software engineering, project management, and agile delivery principles.
- Make work specific, actionable, and testable.
- Avoid placeholders, filler, and vague language.
- Prefer concise, implementation-ready titles.
"""

_DEFAULT_CREATE_PROMPT = """Create a new Jira ticket response for software delivery.
Return output in exactly this format:
SUMMARY: <single-line ticket title>
DESCRIPTION:
## User Story
...
## Requirements
...
## Acceptance Criteria
...
## Agent Context
N/A
## Agent Prompt
N/A

Description heading order:
{{headings_block}}

Description rules:
- Use each heading exactly once as `## <Heading>`.
- Keep the content specific to the requested work.
- Write acceptance criteria that a software engineer or reviewer can verify.
- Include technical guidance only when it helps implementation.
"""

_DEFAULT_EDIT_PROMPT = """Revise Jira ticket content for an existing software delivery issue.
Return output in exactly this format:
SUMMARY: <single-line ticket title>
DESCRIPTION:
## User Story
...
## Requirements
...
## Acceptance Criteria
...
## Agent Context
N/A
## Agent Prompt
N/A

Description heading order:
{{headings_block}}

Editing rules:
- Preserve the issue's intent while improving clarity and delivery readiness.
- Keep user story, requirements, and acceptance criteria aligned with the current request.
- Do not invent unrelated scope.
"""

_DEFAULT_COMMENT_PROMPT = """Write a Jira comment for a software delivery ticket.
Return output in exactly this format:
COMMENT:
<comment markdown>

Comment rules:
- Keep the comment clear, action-oriented, and grounded in the ticket context.
- If the request sounds like a status update, state progress and next steps.
- If the request sounds like an instruction, phrase it so collaborators can act on it.
"""


class JiraContentAgent:
    def __init__(self, registry_mode: str = "codex") -> None:
        self.registry_mode = registry_mode
        self.agent_id = make_agent_id(registry_mode, CONFIG.name)
        self._registered = False
        self.llm = LLMClient()
        self.templates_dir = Path(__file__).resolve().parent / "templates"

    def register(self) -> None:
        if self._registered:
            return
        register_agent(
            AgentDefinition(
                id=self.agent_id,
                name=CONFIG.name,
                provider=None,
                model=get_agent_model("jira_content"),
                group=CONFIG.group,
                role=CONFIG.role,
                kind="subagent",
                dependencies=[],
                source="app/agents_jira_content/runtime.py",
                description=CONFIG.description,
                capabilities=[
                    "jira",
                    "ticket_content_generation",
                    "ticket_title_generation",
                    "ticket_description_generation",
                    "ticket_comment_generation",
                    "agile_ticket_authoring",
                ],
            )
        )
        self._registered = True

    @staticmethod
    def _normalize_whitespace(value: str) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _truncate_text(value: str, max_chars: int) -> str:
        text = JiraContentAgent._normalize_whitespace(value)
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _primary_user_text(user_message: str) -> str:
        text = str(user_message or "")
        marker_index = text.find(ATTACHMENT_CONTEXT_MARKER)
        if marker_index < 0:
            return text
        return text[:marker_index]

    @staticmethod
    def _looks_like_attachment_filename(value: str) -> bool:
        candidate = str(value or "").strip().strip("'\"")
        if not candidate or "/" in candidate or "\\" in candidate:
            return False
        return bool(_ATTACHMENT_FILENAME_RE.fullmatch(candidate))

    @staticmethod
    def _clean_create_title_candidate(raw: str) -> str:
        value = " ".join(str(raw or "").strip().split())
        if not value:
            return ""
        value = re.sub(
            r"\b(?:can you|could you|would you|please|thanks|thank you)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(r"\bon\s+[A-Z][A-Z0-9]+-\d+\b$", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"\bfor\s+[A-Z][A-Z0-9]+-\d+\b$", "", value, flags=re.IGNORECASE).strip()
        value = value.strip(" \t-,:.;")
        lowered = value.lower()
        if lowered.startswith("adding "):
            value = "Add " + value[7:]
        elif lowered.startswith("to add "):
            value = "Add " + value[7:]
        elif lowered.startswith("add "):
            value = "Add " + value[4:]
        elif lowered.startswith("qa"):
            value = "QA " + value[2:].strip() if len(value) > 2 else "QA"
        value = " ".join(value.split()).strip(" \t-,:.;")
        if not value or JiraContentAgent._looks_like_attachment_filename(value):
            return ""
        if value.lower() in {
            "this",
            "that",
            "it",
            "one",
            "same",
            "same one",
            "ticket",
            "issue",
            "task",
            "jira ticket",
            "new ticket",
            "new jira ticket",
        }:
            return ""
        if value.islower():
            value = value[0].upper() + value[1:]
        return value[:180]

    def _load_template(self, filename: str, default_text: str) -> str:
        path = self.templates_dir / filename
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
        return text or default_text.strip()

    @staticmethod
    def _render_template(template: str, context: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = str(match.group(1) or "").strip()
            return str(context.get(key) or "").strip()

        return _TEMPLATE_VAR_RE.sub(replace, template)

    @staticmethod
    def _recent_comments_excerpt(comments: list[dict[str, Any]] | None, max_items: int = 3) -> str:
        if not isinstance(comments, list):
            return "n/a"
        excerpts: list[str] = []
        for item in comments[-max_items:]:
            if not isinstance(item, dict):
                continue
            author = JiraContentAgent._normalize_whitespace(str(item.get("author") or ""))
            body = JiraContentAgent._truncate_text(str(item.get("body") or ""), 220)
            if not body:
                continue
            label = f"{author}: " if author else ""
            excerpts.append(f"- {label}{body}")
        return "\n".join(excerpts) if excerpts else "n/a"

    @staticmethod
    def _normalize_description_with_headings(
        raw_description: str,
        headings: tuple[str, ...],
    ) -> str | None:
        text = str(raw_description or "").strip()
        if not text:
            return None

        heading_pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
        matches = list(heading_pattern.finditer(text))
        if not matches:
            return None

        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            title = str(match.group(1) or "").strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if title in headings and content:
                sections[title] = content

        if any(not sections.get(title) for title in headings):
            return None
        return JiraContentAgent._rebuild_description_from_sections(sections, headings)

    @staticmethod
    def _rebuild_description_from_sections(
        sections: dict[str, str],
        headings: tuple[str, ...],
    ) -> str:
        lines: list[str] = []
        for heading in headings:
            content = str(sections.get(heading) or "").strip() or "N/A"
            lines.append(f"## {heading}")
            lines.append(content)
            lines.append("")
        return "\n".join(lines).strip()

    def _parse_summary_and_description(
        self,
        raw_text: str,
        *,
        headings: tuple[str, ...],
    ) -> tuple[str, str, list[str]]:
        text = str(raw_text or "").strip()
        if not text:
            return "", "", ["Response was empty."]

        errors: list[str] = []
        summary_match = _SUMMARY_LINE_RE.search(text)
        description_marker_match = _DESCRIPTION_MARKER_RE.search(text)

        if not summary_match:
            errors.append("Missing `SUMMARY:` line.")
        if not description_marker_match:
            errors.append("Missing `DESCRIPTION:` marker.")

        summary = self._normalize_whitespace(summary_match.group(1) if summary_match else "")
        if not summary:
            errors.append("Summary was empty.")

        description_source = text[description_marker_match.end() :].strip() if description_marker_match else ""
        description = self._normalize_description_with_headings(description_source, headings) or ""
        if not description:
            errors.append("Description did not match the required heading structure.")

        return summary, description, errors

    def _parse_comment(self, raw_text: str) -> tuple[str, list[str]]:
        text = str(raw_text or "").strip()
        if not text:
            return "", ["Response was empty."]

        errors: list[str] = []
        marker_match = _COMMENT_MARKER_RE.search(text)
        if not marker_match:
            errors.append("Missing `COMMENT:` marker.")
            return "", errors

        comment = text[marker_match.end() :].strip()
        if not comment:
            errors.append("Comment body was empty.")
            return "", errors
        return comment[:3000], errors

    @staticmethod
    def _format_retry_feedback(errors: list[str], raw_text: str) -> str:
        lines = ["The previous attempt failed validation. Fix these issues and return the required format only:"]
        for error in errors:
            lines.append(f"- {error}")
        preview = JiraContentAgent._truncate_text(raw_text, 500)
        if preview:
            lines.append(f"- Previous output preview: {preview}")
        return "\n".join(lines)

    @staticmethod
    def _apply_agent_sections(
        description: str,
        *,
        headings: tuple[str, ...],
        agent_context: str,
        agent_prompt: str,
    ) -> str:
        lines = str(description or "").splitlines()
        sections: dict[str, list[str]] = {}
        current_heading: str | None = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                heading = stripped[3:].strip()
                if heading in headings:
                    current_heading = heading
                    sections.setdefault(heading, [])
                    continue
            if current_heading is not None:
                sections.setdefault(current_heading, []).append(line)

        sections["Agent Context"] = (agent_context.strip() or "N/A").splitlines()
        # Keep the Agent Prompt section intentionally blank in generated tickets.
        sections["Agent Prompt"] = []

        rebuilt: list[str] = []
        for heading in headings:
            rebuilt.append(f"## {heading}")
            if heading == "Agent Prompt":
                rebuilt.append("")
                continue
            content_lines = sections.get(heading) or ["N/A"]
            trimmed_lines = [line.rstrip() for line in content_lines]
            while trimmed_lines and not trimmed_lines[-1].strip():
                trimmed_lines.pop()
            if not trimmed_lines:
                trimmed_lines = ["N/A"]
            rebuilt.extend(trimmed_lines)
            rebuilt.append("")
        return "\n".join(rebuilt).strip()

    async def _generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        llm_errors: list[str] = []
        function_settings = get_llm_function_settings("jira_content_generation")
        if not function_settings:
            function_settings = get_llm_function_settings("jira_description_generation")
        openai_model = str(function_settings.get("openai_model") or "").strip()
        anthropic_model = str(function_settings.get("anthropic_model") or "").strip()

        if self.llm.openai_api_key and openai_model:
            try:
                return await self.llm.openai_response(system_prompt, user_prompt, model=openai_model)
            except Exception as exc:
                llm_errors.append(f"OpenAI: {str(exc).strip() or type(exc).__name__}")
        if self.llm.anthropic_api_key and anthropic_model:
            try:
                return await self.llm.anthropic_response(system_prompt, user_prompt, model=anthropic_model)
            except Exception as exc:
                llm_errors.append(f"Anthropic: {str(exc).strip() or type(exc).__name__}")
        if llm_errors:
            raise RuntimeError("Jira content generation failed: " + " | ".join(llm_errors[:2]))
        raise RuntimeError("Jira content generation unavailable: no provider API key configured.")

    async def _generate_ticket_payload_with_retries(
        self,
        *,
        system_prompt: str,
        base_user_prompt: str,
        headings: tuple[str, ...],
    ) -> dict[str, str]:
        attempt_prompt = base_user_prompt
        last_errors: list[str] = []
        for _attempt in range(_MAX_STRUCTURE_ATTEMPTS):
            raw_text = await self._generate_text(system_prompt=system_prompt, user_prompt=attempt_prompt)
            summary, description, errors = self._parse_summary_and_description(raw_text, headings=headings)
            if not errors:
                return {"summary": summary, "description": description}
            last_errors = errors
            attempt_prompt = base_user_prompt + "\n\n" + self._format_retry_feedback(errors, raw_text)
        raise RuntimeError("Jira content generation failed validation: " + " | ".join(last_errors))

    async def _generate_comment_with_retries(
        self,
        *,
        system_prompt: str,
        base_user_prompt: str,
    ) -> str:
        attempt_prompt = base_user_prompt
        last_errors: list[str] = []
        for _attempt in range(_MAX_STRUCTURE_ATTEMPTS):
            raw_text = await self._generate_text(system_prompt=system_prompt, user_prompt=attempt_prompt)
            comment, errors = self._parse_comment(raw_text)
            if not errors:
                return comment
            last_errors = errors
            attempt_prompt = base_user_prompt + "\n\n" + self._format_retry_feedback(errors, raw_text)
        raise RuntimeError("Jira comment generation failed validation: " + " | ".join(last_errors))

    async def generate_create_ticket_content(
        self,
        *,
        user_message: str,
        requested_summary: str,
        project_key: str = "",
        parent_key: str = "",
        parent_summary: str = "",
        parent_description: str = "",
        workspace_context: str = "",
        agent_prompt: str = "",
    ) -> dict[str, str]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            headings_block = "\n".join(f"- {title}" for title in CREATE_DESCRIPTION_SECTION_TITLES)
            system_prompt = "\n\n".join(
                [
                    self._load_template("shared_principles.md", _DEFAULT_SHARED_PRINCIPLES),
                    self._render_template(
                        self._load_template("create_ticket_prompt.md", _DEFAULT_CREATE_PROMPT),
                        {"headings_block": headings_block},
                    ),
                ]
            ).strip()
            user_prompt = "\n".join(
                [
                    "Context for the new Jira ticket:",
                    f"- Project key: {project_key or 'n/a'}",
                    f"- Requested summary/topic: {requested_summary or 'n/a'}",
                    f"- Parent ticket: {parent_key or 'n/a'}",
                    f"- Parent summary: {parent_summary or 'n/a'}",
                    f"- Parent description/context: {self._truncate_text(parent_description, 700) or 'n/a'}",
                    f"- User request: {self._truncate_text(self._primary_user_text(user_message), 900) or 'n/a'}",
                ]
            ).strip()
            payload = await self._generate_ticket_payload_with_retries(
                system_prompt=system_prompt,
                base_user_prompt=user_prompt,
                headings=CREATE_DESCRIPTION_SECTION_TITLES,
            )
            payload["description"] = self._apply_agent_sections(
                payload.get("description") or "",
                headings=CREATE_DESCRIPTION_SECTION_TITLES,
                agent_context=workspace_context,
                agent_prompt=agent_prompt or self._primary_user_text(user_message).strip() or "N/A",
            )
            return payload
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def generate_subtask_summaries(
        self,
        *,
        user_message: str,
        parent_summary: str,
        parent_description: str = "",
        max_subtasks: int = 5,
    ) -> list[str]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            limit = max(1, min(int(max_subtasks or 5), 8))
            system_prompt = "\n\n".join(
                [
                    self._load_template("shared_principles.md", _DEFAULT_SHARED_PRINCIPLES),
                    (
                        "Plan implementation subtasks for a Jira ticket.\n"
                        "Return only a flat list of concise subtask titles, one per line, prefixed with `- `.\n"
                        f"Return between 3 and {limit} subtasks.\n"
                        "Do not include numbering, explanations, headings, or markdown beyond the bullet prefix.\n"
                        "Make each subtask implementation-ready and distinct."
                    ),
                ]
            ).strip()
            base_user_prompt = "\n".join(
                [
                    "Context for Jira subtask planning:",
                    f"- Parent summary: {parent_summary or 'n/a'}",
                    f"- Parent description/context: {self._truncate_text(parent_description, 900) or 'n/a'}",
                    f"- User request: {self._truncate_text(self._primary_user_text(user_message), 900) or 'n/a'}",
                ]
            ).strip()

            attempt_prompt = base_user_prompt
            last_error = "No subtask titles were returned."
            for _attempt in range(_MAX_STRUCTURE_ATTEMPTS):
                raw_text = await self._generate_text(system_prompt=system_prompt, user_prompt=attempt_prompt)
                titles: list[str] = []
                for line in str(raw_text or "").splitlines():
                    cleaned = re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line).strip()
                    cleaned = self._clean_create_title_candidate(cleaned)
                    if not cleaned or cleaned in titles:
                        continue
                    titles.append(cleaned)
                if titles:
                    return titles[:limit]
                last_error = "Response did not contain any valid subtask titles."
                attempt_prompt = base_user_prompt + "\n\n" + self._format_retry_feedback([last_error], raw_text)
            raise RuntimeError(f"Jira subtask planning failed validation: {last_error}")
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def generate_edit_ticket_content(
        self,
        *,
        user_message: str,
        issue_key: str,
        existing_summary: str,
        existing_description: str = "",
        requested_summary: str = "",
        parent_key: str = "",
        parent_summary: str = "",
        parent_description: str = "",
        workspace_context: str = "",
        agent_prompt: str = "",
    ) -> dict[str, str]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            headings_block = "\n".join(f"- {title}" for title in EDIT_DESCRIPTION_SECTION_TITLES)
            system_prompt = "\n\n".join(
                [
                    self._load_template("shared_principles.md", _DEFAULT_SHARED_PRINCIPLES),
                    self._render_template(
                        self._load_template("edit_ticket_prompt.md", _DEFAULT_EDIT_PROMPT),
                        {"headings_block": headings_block},
                    ),
                ]
            ).strip()
            user_prompt = "\n".join(
                [
                    "Context for the Jira ticket edit:",
                    f"- Issue key: {issue_key or 'n/a'}",
                    f"- Existing summary: {existing_summary or 'n/a'}",
                    f"- Requested summary change: {requested_summary or 'none'}",
                    f"- Existing description excerpt: {self._truncate_text(existing_description, 700) or 'n/a'}",
                    f"- Parent ticket: {parent_key or 'n/a'}",
                    f"- Parent summary: {parent_summary or 'n/a'}",
                    f"- Parent description/context: {self._truncate_text(parent_description, 700) or 'n/a'}",
                    f"- User request: {self._truncate_text(self._primary_user_text(user_message), 900) or 'n/a'}",
                ]
            ).strip()
            payload = await self._generate_ticket_payload_with_retries(
                system_prompt=system_prompt,
                base_user_prompt=user_prompt,
                headings=EDIT_DESCRIPTION_SECTION_TITLES,
            )
            payload["description"] = self._apply_agent_sections(
                payload.get("description") or "",
                headings=EDIT_DESCRIPTION_SECTION_TITLES,
                agent_context=workspace_context,
                agent_prompt=agent_prompt or self._primary_user_text(user_message).strip() or "N/A",
            )
            return payload
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def generate_ticket_comment(
        self,
        *,
        user_message: str,
        issue_key: str,
        issue_summary: str,
        issue_description: str = "",
        comments: list[dict[str, Any]] | None = None,
    ) -> str:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            system_prompt = "\n\n".join(
                [
                    self._load_template("shared_principles.md", _DEFAULT_SHARED_PRINCIPLES),
                    self._load_template("comment_prompt.md", _DEFAULT_COMMENT_PROMPT),
                ]
            ).strip()
            user_prompt = "\n".join(
                [
                    "Context for the Jira comment:",
                    f"- Issue key: {issue_key or 'n/a'}",
                    f"- Issue summary: {issue_summary or 'n/a'}",
                    f"- Issue description excerpt: {self._truncate_text(issue_description, 700) or 'n/a'}",
                    f"- Recent comments: {self._recent_comments_excerpt(comments)}",
                    f"- User request: {self._truncate_text(user_message, 900) or 'n/a'}",
                ]
            ).strip()
            return await self._generate_comment_with_retries(
                system_prompt=system_prompt,
                base_user_prompt=user_prompt,
            )
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)
