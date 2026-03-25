from __future__ import annotations

import asyncio
import html
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from app.agent_registry import (
    AgentDefinition,
    make_agent_id,
    mark_agent_end,
    mark_agent_start,
    register_agent,
)
from app import intent_router as router
from app.agents_cli_agent.runtime import (
    extract_direct_commands,
    run_cli_commands_workflow,
    run_cli_workflow,
)
from app.agents_shared import build_worker_agents
from app.agents_shared.runtime import format_memory_text, slugify_text
from app.agents_code_review.runtime import review_build_attempt
from app.agents_code_builder.runtime import build_codex_skills_prompt, run_codex_exec
from app.agents_git import GitAgent
from app.agents_git_content import GitContentAgent
from app.agents_logging_agent.runtime import log_agent_error_event
from app.agents_planner.runtime import (
    delegate_to_sdd_spec_agent,
    next_pipeline_version,
    normalize_plan_lines,
    sanitize_pipeline_stream_id,
    to_checkbox_lines,
)
from app.agents_research.runtime import run_research_workflow
from app.agents_sdd_spec.runtime import register_sdd_spec_agent
from app.db import (
    add_message,
    add_orchestrator_event,
    conversation_messages,
    create_orchestrator_task,
    list_orchestrator_events,
    list_orchestrator_tasks,
    update_orchestrator_task_status,
)
from app.llm import LLMClient
from app.mcp_client import MCPClient, load_mcp_config
from app.git_workflow_runtime import run_configured_git_action
from app.jira_conversation_state import load_jira_conversation_state
from app.settings_store import get_agent_bypass_settings, get_agent_model
from app.pipeline_store import get_shared_max_retries
from app.workspace import CODE_BUILDER_WORKSPACE_RULES, WorkspaceManager, ensure_workspace_bootstrap
from app.agents_jira_api import JiraApiAgent
from app.agents_slack import SlackAgent

MAX_BUILD_ITERATIONS = int(os.getenv("MAX_BUILD_ITERATIONS", "4"))
CODEX_CLI_OUTPUT_LOG_CHARS = int(os.getenv("CODEX_CLI_OUTPUT_LOG_CHARS", "32000"))
RUN_COMMAND_TIMEOUT_SECONDS = int(os.getenv("CODEX_RUN_COMMAND_TIMEOUT_SECONDS", "1200"))
CODEX_HEARTBEAT_SECONDS = int(os.getenv("CODEX_HEARTBEAT_SECONDS", "30"))
RESEARCH_MAX_QUERIES = int(os.getenv("RESEARCH_MAX_QUERIES", "3"))
RESEARCH_SEARCH_RESULT_COUNT = int(os.getenv("RESEARCH_SEARCH_RESULT_COUNT", "5"))
RESEARCH_FETCH_MAX_URLS = int(os.getenv("RESEARCH_FETCH_MAX_URLS", "3"))
RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS = float(os.getenv("RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS", "8"))
RESEARCH_HTTP_FETCH_MAX_CHARS = int(os.getenv("RESEARCH_HTTP_FETCH_MAX_CHARS", "2400"))
RESEARCH_MCP_CALL_TIMEOUT_SECONDS = float(os.getenv("RESEARCH_MCP_CALL_TIMEOUT_SECONDS", "30"))
RESEARCH_MCP_MAX_RETRIES = int(os.getenv("RESEARCH_MCP_MAX_RETRIES", "1"))

WorkflowModeName = Literal["auto", "jira", "code_review", "code", "research"]

WORKFLOW_MODE_LABELS: dict[WorkflowModeName, str] = {
    "auto": "Auto",
    "jira": "Jira",
    "code_review": "Code Review",
    "code": "Code",
    "research": "Research",
}

WORKFLOW_MODE_INTENTS: dict[WorkflowModeName, str] = {
    "jira": "jira_api",
    "code_review": "read_only_fs",
    "code": "code_build",
    "research": "research_mcp",
}


def _pending_jira_clarification_intent(
    workspace_root: Path,
    conversation_id: str,
    user_message: str,
) -> router.IntentDecision | None:
    state = load_jira_conversation_state(workspace_root, conversation_id)
    pending_action = str(state.pending_clarification_action or "").strip().lower()
    if not pending_action:
        return None
    lowered = str(user_message or "").strip().lower()
    if any(
        router._matches_any(lowered, patterns)
        for patterns in (
            router.WORKSPACE_PATTERNS,
            router.READ_ONLY_FS_PATTERNS,
            router.RUN_COMMAND_PATTERNS,
            router.RESEARCH_PATTERNS,
            router.SLACK_PATTERNS,
        )
    ):
        return None
    if router._looks_like_explicit_git_operation(lowered):
        return None
    if not JiraApiAgent._looks_like_clarification_follow_up(user_message, pending_action):
        return None
    return router.IntentDecision(
        intent="jira_api",
        confidence=0.99,
        reason=f"Detected follow-up answer to pending Jira {pending_action} clarification.",
        source="jira_state",
    )


_SUPPORTED_ORCHESTRATOR_INTENTS = {
    "chat",
    "read_only_fs",
    "run_commands",
    "research_mcp",
    "jira_api",
    "code_build",
    "slack_post",
}


def _normalize_orchestrator_intent(decision: router.IntentDecision) -> router.IntentDecision:
    if decision.intent in _SUPPORTED_ORCHESTRATOR_INTENTS:
        return decision

    return router.IntentDecision(
        intent="chat",
        confidence=min(decision.confidence, 0.6),
        reason=(
            f"{decision.reason} "
            f"Normalized unsupported intent '{decision.intent}' to the safe chat fallback."
        ).strip(),
        source=decision.source,
    )


def _normalize_workflow_mode(workflow_mode: str | None) -> WorkflowModeName:
    normalized = str(workflow_mode or "").strip().lower()
    if normalized in {"jira", "code_review", "code", "research"}:
        return normalized  # type: ignore[return-value]
    return "auto"


def _workflow_mode_switch_reply(workflow_mode: WorkflowModeName) -> str:
    if workflow_mode == "jira":
        return "This conversation is in Jira mode. Switch to Code Review, Code Development, Research, or Auto to handle that request."
    if workflow_mode == "code_review":
        return "This conversation is in Code Review mode. Switch to Code Development, Jira, Research, or Auto to handle that request."
    if workflow_mode == "code":
        return "This conversation is in Code mode. Switch to Code Review, Jira, Research, or Auto to handle that request."
    if workflow_mode == "research":
        return "This conversation is in Research mode. Switch to Code Review, Jira, Code Development, or Auto to handle that request."
    return ""


def _enforce_workflow_mode(
    workflow_mode: WorkflowModeName,
    decision: router.IntentDecision,
) -> tuple[router.IntentDecision | None, str | None]:
    if workflow_mode == "auto":
        return decision, None

    target_intent = WORKFLOW_MODE_INTENTS[workflow_mode]
    if workflow_mode in {"code", "code_review"}:
        mode_label = WORKFLOW_MODE_LABELS[workflow_mode]
        return (
            router.IntentDecision(
                intent=target_intent,
                confidence=max(decision.confidence, 0.99),
                reason=(
                    f"{mode_label} mode is forcing this conversation to use the {target_intent} workflow, "
                    f"overriding detected intent '{decision.intent}'."
                ),
                source="workflow_mode",
            ),
            None,
        )

    if decision.intent != target_intent:
        return None, _workflow_mode_switch_reply(workflow_mode)

    return (
        router.IntentDecision(
            intent=target_intent,
            confidence=max(decision.confidence, 0.99),
            reason=f"{WORKFLOW_MODE_LABELS[workflow_mode]} mode is forcing this conversation to use the {target_intent} workflow.",
            source="workflow_mode",
        ),
        None,
    )


@dataclass
class WorkerAgent:
    name: str
    provider: str
    system_prompt: str
    model: str | None = None
    max_tokens: int | None = None
    agent_id: str | None = None


# DEPRECATED: Replaced by app/graphs/chat/ (ChatGraph + LangGraph StateGraph).
# Do not delete until ChatGraph has been stable across at least one full release cycle.
class OrchestratorEngine:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()
        self.context_prefix = self._load_context_files()
        self.workspace_context_prefix = ""
        self.workflow_id = "codex_builder"

        agents = build_worker_agents(self._settings_model, WorkerAgent)
        self.orchestrator = agents["orchestrator_codex"]
        self.planner = agents["planner_codex"]
        self.research = agents["research_codex"]
        self.code_builder = agents["code_builder_codex"]
        self.code_reviewer = agents["code_reviewer_codex"]
        self.cli_runner = agents["cli_runner_codex"]
        self.logging_agent = agents["logging_agent_codex"]
        self.jira_agent = JiraApiAgent(registry_mode="agents")
        self.jira_agent.register()
        self.git_agent = GitAgent()
        self.git_agent.register()
        self.git_content_agent = GitContentAgent(registry_mode="agents")
        self.git_content_agent.register()
        self.slack_agent = SlackAgent()
        self.slack_agent.register()
        self._register_agents()

    def _load_context_files(self) -> str:
        context_parts: list[str] = []
        config_dir = Path(__file__).resolve().parent.parent / "config"
        config_files = {
            "SYSTEM": "SYSTEM.md",
            "SOUL": "SOUL.md",
            "MEMORY": "MEMORY.md",
            "RULES": "RULES.md",
        }

        for section_name, filename in config_files.items():
            file_path = config_dir / filename

            if not file_path.exists():
                continue

            try:
                content = file_path.read_text(encoding="utf-8").strip()
            except Exception:
                continue

            if content:
                context_parts.append(f"## {section_name}\n\n{content}")

        if context_parts:
            return "\n\n---\n\n".join(context_parts) + "\n\n---\n\n"

        return ""

    async def _run_git_hook(
        self,
        *,
        conversation_id: str,
        stage_id: str,
        workspace_path: str,
        context: dict[str, str],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        result = await run_configured_git_action(
            stage_id=stage_id,
            workspace_path=workspace_path,
            workflow_key="chat",
            context=context,
            git_agent=self.git_agent,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=self.git_agent.agent_id or "Git Agent",
            event_type="git_hook",
            content=json.dumps(
                {
                    "stage": stage_id,
                    "ok": bool(result.get("ok")),
                    "skipped": bool(result.get("skipped")),
                    "action": result.get("action"),
                    "message": str(result.get("message") or result.get("reason") or result.get("error") or ""),
                }
            ),
        )
        if self._git_hook_failed(result):
            self._log_agent_error_event(
                conversation_id=conversation_id,
                task_id=task_id,
                source_agent=self.git_agent.agent_id or "Git Agent",
                error=self._git_hook_error_text(result),
                context={
                    "stage": stage_id,
                    "action": str(result.get("action") or ""),
                    "result": result.get("result") if isinstance(result.get("result"), dict) else result,
                },
            )
        return result

    def _log_agent_error_event(
        self,
        *,
        conversation_id: str,
        source_agent: str,
        error: str,
        task_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        log_agent_error_event(
            conversation_id=conversation_id,
            logger_agent=self.logging_agent.agent_id or self.logging_agent.name,
            task_id=task_id,
            source_agent=source_agent,
            error=error,
            context=context,
        )

    @staticmethod
    def _git_hook_failed(result: dict[str, Any]) -> bool:
        if bool(result.get("ok")):
            return False
        reason = str(result.get("reason") or "").strip().lower()
        return reason != "disabled"

    @staticmethod
    def _git_hook_error_text(result: dict[str, Any]) -> str:
        stage = str(result.get("stage") or "").strip() or "unknown"
        action = str(result.get("action") or "").strip() or "unknown"
        reason = str(result.get("reason") or result.get("message") or result.get("error") or "").strip()
        details = result.get("result") if isinstance(result.get("result"), dict) else {}
        error = str(details.get("error") or "").strip()
        step = str(details.get("step") or "").strip()
        parts = [f"Git hook {stage} ({action}) failed"]
        if step:
            parts.append(f"step={step}")
        if error:
            parts.append(error)
        elif reason:
            parts.append(reason)
        return ": ".join([parts[0], " | ".join(parts[1:])]) if len(parts) > 1 else parts[0]

    def _ensure_git_hook_succeeded(self, result: dict[str, Any]) -> None:
        if self._git_hook_failed(result):
            raise RuntimeError(self._git_hook_error_text(result))

    def _load_workspace_context_files(
        self,
        workspace: WorkspaceManager,
        secondary_workspace: WorkspaceManager | None = None,
    ) -> str:
        context_parts: list[str] = []

        def append_memory_section(target_workspace: WorkspaceManager, label: str) -> None:
            assist_memory_path = target_workspace.root / ".assist" / "MEMORY.md"
            if not assist_memory_path.exists():
                return
            try:
                content = assist_memory_path.read_text(encoding="utf-8").strip()
            except Exception:
                content = ""
            if content:
                context_parts.append(
                    f"## {label} WORKSPACE MEMORY ({target_workspace.root})\n\n{content}"
                )

        append_memory_section(workspace, "PRIMARY")
        if secondary_workspace:
            append_memory_section(secondary_workspace, "SECONDARY")

        if context_parts:
            return "\n\n---\n\n".join(context_parts) + "\n\n---\n\n"
        return ""

    @staticmethod
    def _settings_model(agent_key: str | None) -> str | None:
        if not agent_key:
            return None
        return get_agent_model(agent_key)

    @staticmethod
    def _agent_bypass_flags() -> tuple[bool, bool]:
        bypass = get_agent_bypass_settings()
        return bool(bypass["code_builder"]), bool(bypass["code_review"])

    @staticmethod
    def _shared_retry_limit() -> int:
        try:
            return int(get_shared_max_retries())
        except Exception:
            return max(1, MAX_BUILD_ITERATIONS)

    async def _call(
        self,
        agent: WorkerAgent,
        prompt: str,
        *,
        conversation_id: str | None = None,
        task_id: str | None = None,
    ) -> str:
        if agent.agent_id:
            mark_agent_start(agent.agent_id)
        try:
            enhanced_system_prompt = self.context_prefix + self.workspace_context_prefix + agent.system_prompt
            provider = self._resolve_provider(agent)
            if provider == "anthropic":
                result = await self.llm.anthropic_response(
                    enhanced_system_prompt,
                    prompt,
                    model=agent.model,
                    max_tokens=agent.max_tokens,
                )
            else:
                result = await self.llm.openai_response(
                    enhanced_system_prompt,
                    prompt,
                    model=agent.model,
                )
            if agent.agent_id:
                mark_agent_end(agent.agent_id)
            return result
        except Exception as exc:
            if agent.agent_id:
                mark_agent_end(agent.agent_id, str(exc))
            if conversation_id:
                self._log_agent_error_event(
                    conversation_id=conversation_id,
                    task_id=task_id,
                    source_agent=agent.agent_id or agent.name,
                    error=self._format_exception(exc),
                    context={"phase": "llm_call", "agent_name": agent.name},
                )
            raise

    @staticmethod
    def _resolve_provider(agent: WorkerAgent) -> str:
        model = str(agent.model or "").strip().lower()
        if model.startswith(("gpt-", "o1", "o3", "o4")):
            return "openai"
        if model.startswith("claude"):
            return "anthropic"
        provider = str(agent.provider or "").strip().lower()
        return provider or "openai"

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
            stripped = "\n".join(lines).strip()
        try:
            return json.loads(stripped)
        except Exception:
            pass
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(stripped[start : end + 1])
        except Exception:
            return None

    @staticmethod
    def _truncate_text(value: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(value) <= limit:
            return value
        return f"{value[:limit]}... (truncated, {len(value)} chars total)"

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        text = str(exc).strip()
        if text:
            return text
        return f"{type(exc).__name__}: {repr(exc)}"

    @staticmethod
    def _extract_urls(text: str, limit: int = 6) -> list[str]:
        urls = re.findall(r"https?://[^\s\"')>]+", text)
        unique: list[str] = []
        for url in urls:
            if url not in unique:
                unique.append(url)
            if len(unique) >= limit:
                break
        return unique

    @staticmethod
    def _extract_tools_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not payload:
            return []
        tools = payload.get("tools")
        if isinstance(tools, list):
            return [tool for tool in tools if isinstance(tool, dict)]
        return []

    @staticmethod
    def _pick_tool_from_list(tools: list[dict[str, Any]], keywords: list[str]) -> str | None:
        if not tools:
            return None
        scored: list[tuple[int, str]] = []
        for tool in tools:
            name = str(tool.get("name") or "")
            if not name:
                continue
            score = sum(1 for keyword in keywords if keyword in name.lower())
            scored.append((score, name))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1] if scored[0][0] > 0 else scored[0][1]

    @staticmethod
    def _pick_fetch_tool_from_list(tools: list[dict[str, Any]]) -> str | None:
        if not tools:
            return None
        blocked_tokens = ("close", "delete", "remove", "clear", "stop", "quit")
        preferred_patterns = ("fetch", "read", "extract", "get_content", "scrape", "markdown")
        fallback_patterns = ("open", "navigate", "visit", "goto")
        scored: list[tuple[int, str]] = []
        for tool in tools:
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            lowered = name.lower()
            if any(token in lowered for token in blocked_tokens):
                continue
            score = 0
            if any(token in lowered for token in preferred_patterns):
                score += 3
            if any(token in lowered for token in fallback_patterns):
                score += 1
            scored.append((score, name))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _extract_search_snippets(payload: dict[str, Any]) -> list[str]:
        snippets: list[str] = []
        text = json.dumps(payload or {})
        for key in ("description", "snippet", "summary"):
            for match in re.finditer(rf'"{key}"\s*:\s*"([^"]+)"', text):
                candidate = html.unescape(match.group(1)).strip()
                if candidate and candidate not in snippets:
                    snippets.append(candidate)
        return snippets

    @staticmethod
    def _search_results_need_fetch(search_results: list[dict[str, Any]]) -> bool:
        snippets: list[str] = []
        for entry in search_results:
            result = entry.get("result")
            if isinstance(result, dict):
                snippets.extend(OrchestratorEngine._extract_search_snippets(result))
        if len(snippets) >= 3:
            return False
        snippet_chars = sum(len(item) for item in snippets)
        return snippet_chars < 500

    @staticmethod
    def _user_explicitly_requests_browser(user_message: str) -> bool:
        lowered = (user_message or "").lower()
        tokens = (
            "open browser",
            "use browser",
            "playwright",
            "log in",
            "login",
            "sign in",
            "authenticate",
            "auth",
        )
        return any(token in lowered for token in tokens)

    async def _run_mcp_tool_with_retry(
        self,
        *,
        conversation_id: str,
        workspace: WorkspaceManager,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        agent_name: str,
    ) -> dict[str, Any]:
        attempts = max(1, RESEARCH_MCP_MAX_RETRIES + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    self._run_mcp_tool(
                        conversation_id,
                        None,
                        workspace,
                        server_name,
                        tool_name,
                        arguments,
                        agent_name=agent_name,
                    ),
                    timeout=RESEARCH_MCP_CALL_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    break
                await asyncio.sleep(min(2.0, 0.5 * (attempt + 1)))
        assert last_exc is not None
        raise last_exc

    @staticmethod
    async def _http_fetch_url(url: str) -> dict[str, Any]:
        timeout = httpx.Timeout(
            connect=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
            read=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
            write=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
            pool=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; AIMultiAgentResearch/1.0; +https://example.local)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            content_type = (response.headers.get("content-type") or "").lower()
            text = response.text or ""
            if "html" in content_type:
                text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
                text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
                text = re.sub(r"(?is)<[^>]+>", " ", text)
                text = html.unescape(text)
            cleaned = re.sub(r"\s+", " ", text).strip()
            excerpt = cleaned[:RESEARCH_HTTP_FETCH_MAX_CHARS]
            auth_required = response.status_code in {401, 403, 407} or "captcha" in cleaned.lower()
            return {
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": content_type,
                "auth_required": auth_required,
                "excerpt": excerpt,
            }

    @staticmethod
    def _build_search_arguments(tool: dict[str, Any], query: str) -> dict[str, Any]:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            return {"query": query, "count": RESEARCH_SEARCH_RESULT_COUNT}
        args: dict[str, Any] = {}
        if "query" in props:
            args["query"] = query
        elif "q" in props:
            args["q"] = query
        elif "text" in props:
            args["text"] = query
        elif "input" in props:
            args["input"] = query
        else:
            args["query"] = query
        if "count" in props:
            args["count"] = RESEARCH_SEARCH_RESULT_COUNT
        elif "limit" in props:
            args["limit"] = RESEARCH_SEARCH_RESULT_COUNT
        elif "num_results" in props:
            args["num_results"] = RESEARCH_SEARCH_RESULT_COUNT
        return args

    @staticmethod
    def _build_fetch_arguments(tool: dict[str, Any], url: str) -> dict[str, Any]:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            return {"url": url}
        if "url" in props:
            return {"url": url}
        if "input" in props:
            return {"input": url}
        if "href" in props:
            return {"href": url}
        return {"url": url}

    def _write_workspace_file(
        self,
        conversation_id: str,
        task_id: str | None,
        workspace: WorkspaceManager,
        relative_path: str,
        content: str,
        agent: str | None = None,
    ) -> None:
        workspace.write_text(relative_path, content)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=agent or self.orchestrator.name,
            event_type="file_write",
            content=f"Wrote {relative_path}",
        )

    @staticmethod
    def _slugify_text(text: str, max_words: int = 6) -> str:
        return slugify_text(text, max_words=max_words)

    @staticmethod
    def _sanitize_pipeline_stream_id(value: str, fallback: str = "chat") -> str:
        return sanitize_pipeline_stream_id(value, fallback=fallback)

    @staticmethod
    def _normalize_plan_lines(value: Any) -> list[str]:
        return normalize_plan_lines(value)

    @staticmethod
    def _to_checkbox_lines(lines: list[str]) -> list[str]:
        return to_checkbox_lines(lines)

    def _next_pipeline_version(self, workspace: WorkspaceManager, stream_id: str) -> int:
        return next_pipeline_version(workspace, stream_id)

    async def _write_chat_sdd_bundle(
        self,
        *,
        conversation_id: str,
        user_message: str,
        memory_text: str,
        workspace: WorkspaceManager,
        selected_ticket_contexts: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        return await delegate_to_sdd_spec_agent(
            self,
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
            selected_ticket_contexts=selected_ticket_contexts,
        )

    def _emit_task_event(
        self,
        conversation_id: str,
        task_id: str | None,
        agent: str,
        event_type: str,
        payload: dict[str, Any] | str,
    ) -> None:
        content = payload if isinstance(payload, str) else json.dumps(payload)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=agent,
            event_type=event_type,
            content=content,
        )

    def _set_task_status(self, conversation_id: str, task_id: str, agent: str, status: str) -> None:
        updated = update_orchestrator_task_status(task_id, status)
        payload = {"task_id": task_id, "status": status}
        if updated:
            payload.update(
                {
                    "title": updated.get("title"),
                    "owner_agent": updated.get("owner_agent"),
                }
            )
        self._emit_task_event(conversation_id, task_id, agent, "task_status", payload)

    def _register_agents(self) -> None:
        group = "agents"
        orchestrator_id = make_agent_id(group, self.orchestrator.name)
        planner_id = make_agent_id(group, self.planner.name)
        sdd_spec_id = make_agent_id(group, "SDD Spec Agent")
        research_id = make_agent_id(group, self.research.name)
        code_builder_id = make_agent_id(group, self.code_builder.name)
        code_review_id = make_agent_id(group, self.code_reviewer.name)
        cli_runner_id = make_agent_id(group, self.cli_runner.name)
        logging_id = make_agent_id(group, self.logging_agent.name)

        self.orchestrator.agent_id = orchestrator_id
        self.planner.agent_id = planner_id
        self.research.agent_id = research_id
        self.code_builder.agent_id = code_builder_id
        self.code_reviewer.agent_id = code_review_id
        self.cli_runner.agent_id = cli_runner_id
        self.logging_agent.agent_id = logging_id

        register_agent(
            AgentDefinition(
                id=orchestrator_id,
                name=self.orchestrator.name,
                provider=self.orchestrator.provider,
                model=self.orchestrator.model,
                group=group,
                role="orchestrator",
                kind="agent",
                dependencies=[],
                source="app/agents_orchestrator/runtime.py",
                description="Owns the autonomous workflow and final response.",
                capabilities=["coordination", "synthesis"],
            )
        )
        register_agent(
            AgentDefinition(
                id=planner_id,
                name=self.planner.name,
                provider=self.planner.provider,
                model=self.planner.model,
                group=group,
                role="planner",
                kind="subagent",
                dependencies=[orchestrator_id],
                source="app/agents_planner/runtime.py",
                description="Supports intent fallback and planning prompts.",
                capabilities=["planning", "triage"],
            )
        )
        register_sdd_spec_agent(
            group=group,
            dependency_ids=[planner_id],
            model=get_agent_model("sdd_spec"),
        )
        register_agent(
            AgentDefinition(
                id=research_id,
                name=self.research.name,
                provider=self.research.provider,
                model=self.research.model,
                group=group,
                role="research",
                kind="subagent",
                dependencies=[orchestrator_id],
                source="app/agents_research/runtime.py",
                description="Runs research branch planning, query generation, and synthesis.",
                capabilities=["research", "search_queries", "synthesis", "citations"],
            )
        )
        register_agent(
            AgentDefinition(
                id=code_builder_id,
                name=self.code_builder.name,
                provider=self.code_builder.provider,
                model=self.code_builder.model,
                group=group,
                role="code_builder",
                kind="agent",
                dependencies=[planner_id, sdd_spec_id],
                source="app/orchestrator.py",
                description="Runs autonomous CLI implementation and validation.",
                capabilities=["codex_cli", "implementation", "validation"],
            )
        )
        register_agent(
            AgentDefinition(
                id=code_review_id,
                name=self.code_reviewer.name,
                provider=self.code_reviewer.provider,
                model=self.code_reviewer.model,
                group=group,
                role="code_review",
                kind="subagent",
                dependencies=[code_builder_id],
                source="app/agents_code_review/runtime.py",
                description="Reviews build output and requests fixes when needed.",
                capabilities=["review", "quality"],
            )
        )
        register_agent(
            AgentDefinition(
                id=cli_runner_id,
                name=self.cli_runner.name,
                provider=self.cli_runner.provider,
                model=self.cli_runner.model,
                group=group,
                role="cli_agent",
                kind="subagent",
                dependencies=[orchestrator_id],
                source="app/agents_cli_agent/runtime.py",
                description="Handles explicit run-commands branch execution.",
                capabilities=["cli", "commands"],
            )
        )
        register_agent(
            AgentDefinition(
                id=logging_id,
                name=self.logging_agent.name,
                provider=self.logging_agent.provider,
                model=self.logging_agent.model,
                group=group,
                role="logger",
                kind="subagent",
                dependencies=[orchestrator_id, planner_id, sdd_spec_id, research_id, code_builder_id, code_review_id, cli_runner_id],
                source="app/agents_logging_agent/runtime.py",
                description="Tracks workflow events.",
                capabilities=["logging", "audit"],
            )
        )
        # Slack agent is self-registering (done in __init__); no duplicate registration needed here.

    async def _run_general_workflow(
        self,
        conversation_id: str,
        user_message: str,
        memory: list[dict[str, str]],
    ) -> dict[str, object]:
        memory_text = format_memory_text(memory, limit=len(memory))
        prompt = (
            f"User request:\n{user_message}\n\n"
            f"Recent memory:\n{memory_text or '(none)'}\n\n"
            "Respond to the user now."
        )
        final_reply = await self._call(self.orchestrator, prompt, conversation_id=conversation_id)
        add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=final_reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="assistant_message",
            content=final_reply,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )
        return {
            "reply": final_reply,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }

    async def _run_read_only_fs_workflow(
        self,
        conversation_id: str,
        user_message: str,
        workspace: WorkspaceManager,
    ) -> dict[str, object]:
        commands = ["find . -print | sort", "find . -type f | wc -l", "find . -type d | wc -l"]
        return await self._run_cli_commands_workflow(
            conversation_id=conversation_id,
            user_message=user_message,
            workspace=workspace,
            commands=commands,
            intent_label="read_only_fs",
        )

    async def _run_codex_review_workflow(
        self,
        conversation_id: str,
        user_message: str,
        workspace: WorkspaceManager,
    ) -> dict[str, object]:
        task = create_orchestrator_task(
            conversation_id=conversation_id,
            title="Codex CLI review (read-only)",
            details="Analyze the workspace with Codex CLI in read-only sandbox mode.",
            owner_agent=self.code_reviewer.name,
        )
        self._emit_task_event(conversation_id, task["id"], self.code_reviewer.name, "task_created", task)
        self._set_task_status(conversation_id, task["id"], self.code_reviewer.name, "in_progress")

        review_prompt = (
            "You are in Code Review (Ask) mode.\n"
            "Use read-only analysis only.\n"
            "Do not attempt to create, edit, or delete files.\n"
            "Do not run commands that modify the repository or environment.\n"
            "Inspect the workspace and answer the user clearly with findings, risks, and recommendations.\n\n"
            f"User request:\n{user_message}\n"
        )

        result = await asyncio.to_thread(
            run_codex_exec,
            review_prompt,
            workspace.root,
            self.code_reviewer.model,
            agent_id=self.code_reviewer.agent_id,
            sandbox_mode="read-only",
            bypass_approvals_and_sandbox=False,
        )

        combined_output = (
            f"command: {result.command}\n"
            f"exit: {result.exit_code}\n"
            f"duration_ms: {result.duration_ms}\n\n"
            f"stdout:\n{result.stdout}\n\n"
            f"stderr:\n{result.stderr}\n\n"
            f"last_message:\n{result.last_message}"
        )

        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task["id"],
            agent=self.code_reviewer.name,
            event_type="codex_cli_run",
            content=f"Read-only review run finished with exit {result.exit_code}.",
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task["id"],
            agent=self.code_reviewer.name,
            event_type="codex_cli_output",
            content=self._truncate_text(combined_output, CODEX_CLI_OUTPUT_LOG_CHARS),
        )

        self._set_task_status(
            conversation_id,
            task["id"],
            self.code_reviewer.name,
            "done" if int(result.exit_code) == 0 else "blocked",
        )

        summary_prompt = (
            f"User request:\n{user_message}\n\n"
            "Review mode: Codex CLI read-only sandbox.\n\n"
            f"Codex CLI output:\n{combined_output[:12000]}\n\n"
            "Respond with a clear, well-structured review. Do not claim code changes were made."
        )
        final_reply = await self._call(self.orchestrator, summary_prompt, conversation_id=conversation_id)
        add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=final_reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="assistant_message",
            content=final_reply,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )

        return {
            "reply": final_reply,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }

    @staticmethod
    def _extract_direct_commands(message: str) -> list[str]:
        return extract_direct_commands(message)

    async def _run_run_workflow(
        self,
        conversation_id: str,
        user_message: str,
        workspace: WorkspaceManager,
    ) -> dict[str, object]:
        return await run_cli_workflow(self, conversation_id, user_message, workspace)

    async def _run_cli_commands_workflow(
        self,
        conversation_id: str,
        user_message: str,
        workspace: WorkspaceManager,
        commands: list[str],
        intent_label: str,
    ) -> dict[str, object]:
        return await run_cli_commands_workflow(
            self,
            conversation_id=conversation_id,
            user_message=user_message,
            workspace=workspace,
            commands=commands,
            intent_label=intent_label,
        )

    async def _run_mcp_tool(
        self,
        conversation_id: str,
        task_id: str | None,
        workspace: WorkspaceManager,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        config = load_mcp_config(workspace.root)
        if not config or not config.servers:
            raise RuntimeError("MCP not configured. Add app/mcp.json with at least one server.")
        client = MCPClient(config)
        result = await asyncio.to_thread(client.call_tool, server_name, tool_name, arguments)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=agent_name or self.orchestrator.name,
            event_type="mcp_tool",
            content=json.dumps(
                {
                    "server": server_name,
                    "tool": tool_name,
                    "arguments": arguments,
                    "result_preview": str(result)[:1200],
                }
            ),
        )
        return result

    async def _run_research_workflow(
        self,
        conversation_id: str,
        user_message: str,
        memory: list[dict[str, str]],
        workspace: WorkspaceManager,
    ) -> dict[str, object]:
        return await run_research_workflow(self, conversation_id, user_message, memory, workspace)

    async def _run_jira_workflow(
        self,
        conversation_id: str,
        user_message: str,
        memory: list[dict[str, str]],
        workspace: WorkspaceManager,
        selected_ticket_keys: list[str] | None = None,
    ) -> dict[str, object]:
        task = create_orchestrator_task(
            conversation_id=conversation_id,
            title="Jira ticket operation",
            details=f"Execute Jira request: {user_message}",
            owner_agent="Jira REST API Agent",
        )
        self._emit_task_event(conversation_id, task["id"], "Jira REST API Agent", "task_created", task)
        self._set_task_status(conversation_id, task["id"], "Jira REST API Agent", "in_progress")

        try:
            jira_result = await self.jira_agent.handle_ticket_request(
                workspace.root,
                user_message,
                conversation_memory=memory,
                conversation_id=conversation_id,
                selected_ticket_keys=selected_ticket_keys,
            )
        except Exception as exc:
            self._set_task_status(conversation_id, task["id"], "Jira REST API Agent", "blocked")
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=task["id"],
                agent="Jira REST API Agent",
                event_type="task_failed",
                content=self._format_exception(exc),
            )
            raise

        self._set_task_status(conversation_id, task["id"], "Jira REST API Agent", "done")
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task["id"],
            agent="Jira REST API Agent",
            event_type="jira_action",
            content=json.dumps(
                {
                    "action": jira_result.get("action"),
                    "server": jira_result.get("server"),
                    "tool": jira_result.get("tool"),
                    "issue_key": jira_result.get("issue_key"),
                    "issue_keys": jira_result.get("issue_keys"),
                    "requested_issue_keys": jira_result.get("requested_issue_keys"),
                    "updated_issue_keys": jira_result.get("updated_issue_keys"),
                    "failed_issue_keys": jira_result.get("failed_issue_keys"),
                    "ticket_count": jira_result.get("ticket_count"),
                    "operation_summary": jira_result.get("operation_summary"),
                    "warnings": jira_result.get("warnings"),
                }
            ),
        )

        final_reply = JiraApiAgent.format_chat_reply(jira_result)
        add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=final_reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="assistant_message",
            content=final_reply,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )
        return {
            "reply": final_reply,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }

    async def _run_codex_build_workflow(
        self,
        conversation_id: str,
        user_message: str,
        memory: list[dict[str, str]],
        workspace: WorkspaceManager,
        secondary_workspace: WorkspaceManager | None = None,
        selected_ticket_contexts: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        memory_text = format_memory_text(memory, limit=len(memory))
        secondary_workspace_snapshot = ""
        secondary_workspace_details = ""
        if secondary_workspace is not None:
            secondary_workspace_snapshot = secondary_workspace.list_tree(".", max_depth=3)
            secondary_workspace_details = (
                f"Reference workspace root [secondary]: {secondary_workspace.root}\n"
                "The secondary workspace is read-only. Use it for pattern lookup only.\n"
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="workspace_reference",
                content=f"[secondary] Reference workspace set to {secondary_workspace.root} (read-only).",
            )
        sdd_bundle = await self._write_chat_sdd_bundle(
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
            selected_ticket_contexts=selected_ticket_contexts,
        )
        planned_tasks = str(sdd_bundle.get("tasks_markdown") or "")

        task = create_orchestrator_task(
            conversation_id=conversation_id,
            title="Autonomous build",
            details="Implement, build, and test using Code Builder Codex.",
            owner_agent=self.code_builder.name,
        )
        self._emit_task_event(conversation_id, task["id"], self.code_builder.name, "task_created", task)
        self._set_task_status(conversation_id, task["id"], self.code_builder.name, "in_progress")

        attempt_summaries: list[str] = []
        review_feedback = ""
        review_summary = ""
        success = False
        code_builder_bypass, code_review_bypass = self._agent_bypass_flags()
        bypassed_once = False
        codex_skills_prompt = build_codex_skills_prompt()
        planning_git_hook_ran = False
        max_retries = self._shared_retry_limit()
        attempts_running = 0
        attempts_completed = 0
        attempts_failed = 0

        for attempt in range(1, max_retries + 1):
            attempts_running = 1
            if not planning_git_hook_ran:
                planning_git_hook_ran = True
                planning_git_hook = await self._run_git_hook(
                    conversation_id=conversation_id,
                    task_id=str(task.get("id") or ""),
                    stage_id="planning",
                    workspace_path=str(workspace.root),
                    context={
                        "description": user_message[:120],
                        "summary": planned_tasks[:240],
                        "type": "chat",
                    },
                )
                self._ensure_git_hook_succeeded(planning_git_hook)
            if code_builder_bypass:
                if bypassed_once:
                    break
                bypassed_once = True
                combined_output = (
                    "Code Builder Codex bypassed. No CLI implementation executed for this run.\n"
                    f"Attempt: {attempt}/{max_retries}"
                )
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=task["id"],
                    agent=self.code_builder.name,
                    event_type="agent_bypassed",
                    content="Code Builder Codex bypass is enabled. Request passed to Code Review Agent.",
                )
                codex_exit_code = 0
            else:
                codex_prompt = (
                    "You are Code Builder Codex running inside the project workspace.\n"
                    "Implement the user's request autonomously.\n"
                    "Run the necessary local setup/build/lint/test commands and fix issues you find.\n"
                    "Prefer non-interactive command variants.\n"
                    "Do not write to the secondary workspace.\n"
                    "At the end, provide a concise summary of what changed and validation results.\n\n"
                    f"{CODE_BUILDER_WORKSPACE_RULES}\n"
                    f"{codex_skills_prompt}"
                    f"User request:\n{user_message}\n\n"
                    f"Primary workspace root [primary]: {workspace.root}\n"
                    f"{secondary_workspace_details}\n"
                    "Spec-Driven Development files (treat as the primary implementation contract):\n"
                    f"- requirements.md: {sdd_bundle['requirements_path']}\n"
                    f"- design.md: {sdd_bundle['design_path']}\n"
                    f"- tasks.md: {sdd_bundle['tasks_path']}\n\n"
                    f"Implementation checklist:\n{planned_tasks}\n\n"
                    f"Recent memory:\n{memory_text or '(none)'}\n\n"
                    f"Primary workspace snapshot [primary]:\n{workspace.list_tree('.', max_depth=3)}\n\n"
                    f"{f'Secondary workspace snapshot [secondary]:\\n{secondary_workspace_snapshot}\\n\\n' if secondary_workspace_snapshot else ''}"
                    f"Attempt: {attempt}/{max_retries}\n"
                )
                if review_feedback:
                    codex_prompt += (
                        "\nAdditional repair feedback to address (additive to original requirements/design/tasks):\n"
                        f"{review_feedback}\n"
                    )

                heartbeat_interval = max(5, CODEX_HEARTBEAT_SECONDS)
                attempt_started = asyncio.get_running_loop().time()
                heartbeat_count = 0
                codex_agent_id = self.code_builder.agent_id
                if codex_agent_id:
                    mark_agent_start(codex_agent_id)
                codex_future = asyncio.create_task(
                    asyncio.to_thread(
                        run_codex_exec,
                        codex_prompt,
                        workspace.root,
                        self.code_builder.model,
                    )
                )
                try:
                    while True:
                        try:
                            result = await asyncio.wait_for(asyncio.shield(codex_future), timeout=heartbeat_interval)
                            break
                        except asyncio.TimeoutError:
                            heartbeat_count += 1
                            elapsed_seconds = int(asyncio.get_running_loop().time() - attempt_started)
                            add_orchestrator_event(
                                conversation_id=conversation_id,
                                task_id=task["id"],
                                agent=self.code_builder.name,
                                event_type="codex_heartbeat",
                                content=(
                                    f"Attempt {attempt}/{max_retries} still running "
                                    f"({elapsed_seconds}s elapsed, heartbeat {heartbeat_count})."
                                ),
                            )
                except Exception as exc:
                    if not codex_future.done():
                        codex_future.cancel()
                        with suppress(asyncio.CancelledError):
                            await codex_future
                    if codex_agent_id:
                        mark_agent_end(codex_agent_id, self._format_exception(exc))
                    self._log_agent_error_event(
                        conversation_id=conversation_id,
                        task_id=task["id"],
                        source_agent=codex_agent_id or self.code_builder.name,
                        error=self._format_exception(exc),
                        context={"phase": "codex_exec"},
                    )
                    raise
                if codex_agent_id:
                    mark_agent_end(codex_agent_id)
                combined_output = (
                    f"command: {result.command}\n"
                    f"exit: {result.exit_code}\n"
                    f"duration_ms: {result.duration_ms}\n\n"
                    f"stdout:\n{result.stdout}\n\n"
                    f"stderr:\n{result.stderr}\n\n"
                    f"last_message:\n{result.last_message}"
                )
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=task["id"],
                    agent=self.code_builder.name,
                    event_type="codex_cli_run",
                    content=f"[primary] Builder attempt {attempt} finished with exit {result.exit_code}.",
                )
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=task["id"],
                    agent=self.code_builder.name,
                    event_type="codex_cli_output",
                    content=self._truncate_text(combined_output, CODEX_CLI_OUTPUT_LOG_CHARS),
                )
                codex_exit_code = int(result.exit_code)

            build_git_hook = await self._run_git_hook(
                conversation_id=conversation_id,
                task_id=str(task.get("id") or ""),
                stage_id="build",
                workspace_path=str(workspace.root),
                context={
                    "description": user_message[:120],
                    "summary": combined_output[:240],
                    "type": "chat",
                },
            )
            self._ensure_git_hook_succeeded(build_git_hook)
            review_result = await review_build_attempt(
                self,
                conversation_id=conversation_id,
                task_id=task["id"],
                user_message=user_message,
                workspace=workspace,
                combined_output=(
                    f"{combined_output}\n\n"
                    f"{f'Secondary workspace root [secondary]: {secondary_workspace.root}\\n' if secondary_workspace else ''}"
                    f"{f'Secondary workspace snapshot [secondary]:\\n{secondary_workspace_snapshot}\\n' if secondary_workspace_snapshot else ''}"
                ),
                code_review_bypass=code_review_bypass,
                secondary_workspace_path=str(secondary_workspace.root) if secondary_workspace else None,
                spec_paths={
                    "requirements_path": str(sdd_bundle.get("requirements_path") or ""),
                    "design_path": str(sdd_bundle.get("design_path") or ""),
                    "tasks_path": str(sdd_bundle.get("tasks_path") or ""),
                },
            )
            passed = bool(review_result.get("passed"))
            notes = str(review_result.get("notes") or "").strip()
            fix_instructions = str(review_result.get("fix_instructions") or "").strip()

            attempt_summaries.append(
                f"Attempt {attempt}: codex_exit={codex_exit_code}, review_passed={passed}."
            )

            if passed and codex_exit_code == 0:
                review_summary = notes or "Code Review Agent passed."
                success = True
                attempts_running = 0
                attempts_completed = 1
                break

            review_feedback_parts = []
            if codex_exit_code != 0:
                review_feedback_parts.append(
                    f"Builder CLI exited with {codex_exit_code}. Resolve command/runtime failures."
                )
            if notes:
                review_feedback_parts.append(f"Review notes:\n{notes}")
            if fix_instructions:
                review_feedback_parts.append(f"Fix instructions:\n{fix_instructions}")
            review_feedback = "\n\n".join(review_feedback_parts).strip() or "Address all quality and build issues."
            review_summary = review_feedback
            attempts_running = 0
            attempts_failed += 1
            if code_builder_bypass:
                break

        self._set_task_status(
            conversation_id,
            task["id"],
            self.code_builder.name,
            "done" if success else "blocked",
        )

        task_result_message = "\n".join(attempt_summaries)
        add_message(
            conversation_id,
            role="assistant",
            agent=self.code_builder.name,
            content=task_result_message,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task["id"],
            agent=self.code_builder.name,
            event_type="task_completed" if success else "task_failed",
            content=(review_summary or task_result_message)[:1800],
        )
        if success:
            review_git_hook = await self._run_git_hook(
                conversation_id=conversation_id,
                task_id=str(task.get("id") or ""),
                stage_id="review",
                workspace_path=str(workspace.root),
                context={
                    "description": user_message[:120],
                    "summary": review_summary[:240],
                    "type": "chat",
                },
            )
            self._ensure_git_hook_succeeded(review_git_hook)

        final_prompt = (
            f"User request:\n{user_message}\n\n"
            f"Primary workspace root [primary]: {workspace.root}\n"
            f"{secondary_workspace_details}\n"
            "Spec-Driven Development files:\n"
            f"- requirements.md: {sdd_bundle['requirements_path']}\n"
            f"- design.md: {sdd_bundle['design_path']}\n"
            f"- tasks.md: {sdd_bundle['tasks_path']}\n\n"
            f"Task plan:\n{planned_tasks}\n\n"
            f"Execution summary:\n{task_result_message}\n\n"
            f"Review summary:\n{review_summary or '(none)'}\n\n"
            f"Primary workspace snapshot [primary]:\n{workspace.list_tree('.', max_depth=3)}\n\n"
            f"{f'Secondary workspace snapshot [secondary]:\\n{secondary_workspace_snapshot}\\n\\n' if secondary_workspace_snapshot else ''}"
            "Respond to the user now with what was done, current status, and next steps."
        )
        final_reply = await self._call(self.orchestrator, final_prompt, conversation_id=conversation_id)
        add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=final_reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="assistant_message",
            content=final_reply,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )

        slack_lines = ["Orchestrator build workflow"]
        request_excerpt = user_message.strip()
        if request_excerpt:
            slack_lines.append(f"Request: {request_excerpt[:240]}")
        slack_lines.append(f"Attempts: {len(attempt_summaries)}/{max_retries}")
        slack_lines.append(
            f"Loop states: running={attempts_running} completed={attempts_completed} failed={attempts_failed}"
        )
        slack_lines.append(f"Task request met: {'yes' if success else 'no'}")
        if success:
            slack_lines.extend(["", "Built:", final_reply[:1800]])
        else:
            failure_detail = (review_summary or task_result_message or "Unknown failure").strip()
            slack_lines.extend(["", "Task request unmet:", failure_detail[:1400]])
            if final_reply.strip():
                slack_lines.extend(["", "Summary:", final_reply[:1200]])

        await self.slack_agent.notify_build_complete(
            summary="\n".join(slack_lines)[:3500],
            success=success,
            conversation_id=conversation_id,
        )

        return {
            "reply": final_reply,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }

    async def _run_slack_workflow(
        self,
        conversation_id: str,
        user_message: str,
        memory: list[dict[str, str]],
    ) -> dict[str, object]:
        task = create_orchestrator_task(
            conversation_id=conversation_id,
            title="Post message to Slack",
            details=f"Send a Slack message based on: {user_message}",
            owner_agent="Slack Agent",
        )
        self._emit_task_event(conversation_id, task["id"], "Slack Agent", "task_created", task)
        self._set_task_status(conversation_id, task["id"], "Slack Agent", "in_progress")

        if not self.slack_agent.is_configured():
            note = (
                "Slack is not configured. Set SLACK_BOT_TOKEN and SLACK_DEFAULT_CHANNEL "
                "in your environment to enable Slack messaging."
            )
            self._set_task_status(conversation_id, task["id"], "Slack Agent", "blocked")
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=task["id"],
                agent="Slack Agent",
                event_type="task_failed",
                content=note,
            )
            add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=note)
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="assistant_message",
                content=note,
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="turn_completed",
                content="Turn complete and response returned to user.",
            )
            return {
                "reply": note,
                "tasks": list_orchestrator_tasks(conversation_id),
                "events": list_orchestrator_events(conversation_id),
            }

        memory_text = format_memory_text(memory, limit=len(memory))
        extract_prompt = (
            f"User request:\n{user_message}\n\n"
            f"Recent memory:\n{memory_text or '(none)'}\n\n"
            "Extract the Slack posting intent. Return JSON only as "
            "{\"channel\":\"#channel-name or empty string\","
            "\"message\":\"the exact message to post\"}.\n"
            "Rules:\n"
            "- channel: use the channel the user specified, or empty string for default\n"
            "- message: the message content to post verbatim (no extra commentary)"
        )
        extract_raw = await self._call(self.orchestrator, extract_prompt, conversation_id=conversation_id)
        payload = self._extract_json(extract_raw) or {}
        channel = str(payload.get("channel") or "").strip()
        message_text = str(payload.get("message") or "").strip()

        if not message_text:
            message_text = user_message

        from app.agents_slack.agent import SLACK_DEFAULT_CHANNEL
        target_channel = channel or SLACK_DEFAULT_CHANNEL

        try:
            result = await self.slack_agent.post_message(target_channel, message_text)
            ts = result.get("ts", "")
            self._set_task_status(conversation_id, task["id"], "Slack Agent", "done")
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=task["id"],
                agent="Slack Agent",
                event_type="slack_message_sent",
                content=json.dumps({"channel": target_channel, "ts": ts}),
            )
            final_reply = (
                f"Message posted to Slack channel `{target_channel}`."
                + (f" (ts: `{ts}`)" if ts else "")
            )
        except Exception as exc:
            error_text = self._format_exception(exc)
            self._set_task_status(conversation_id, task["id"], "Slack Agent", "blocked")
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=task["id"],
                agent="Slack Agent",
                event_type="task_failed",
                content=error_text,
            )
            final_reply = f"Failed to post to Slack: {error_text}"

        add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=final_reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="assistant_message",
            content=final_reply,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=self.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )
        return {
            "reply": final_reply,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }

    async def run_turn(
        self,
        conversation_id: str,
        user_message: str,
        workspace_root: str | None = None,
        secondary_workspace_root: str | None = None,
        workflow_mode: str | None = None,
        attachment_context: str = "",
        selected_ticket_keys: list[str] | None = None,
        selected_ticket_contexts: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        workspace: WorkspaceManager | None = None
        secondary_workspace: WorkspaceManager | None = None
        try:
            memory = conversation_messages(conversation_id)
            conversation_memory = memory
            workspace = (
                WorkspaceManager(workspace_root, mode="read_write")
                if workspace_root
                else WorkspaceManager(mode="read_write")
            )
            if secondary_workspace_root and str(secondary_workspace_root).strip():
                resolved_secondary_root = str(secondary_workspace_root).strip()
                if Path(resolved_secondary_root).resolve() != workspace.root:
                    secondary_workspace = WorkspaceManager(
                        resolved_secondary_root,
                        mode="read_only",
                    )
                    if not secondary_workspace.root.exists() or not secondary_workspace.root.is_dir():
                        raise ValueError(
                            f"Secondary workspace path is not a directory: {secondary_workspace.root}"
                        )
            self.workspace_context_prefix = self._load_workspace_context_files(
                workspace,
                secondary_workspace,
            )
            effective_user_message = user_message
            if attachment_context.strip():
                effective_user_message = f"{user_message.strip()}\n\n{attachment_context.strip()}"
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=None,
                    agent=self.orchestrator.name,
                    event_type="user_attachments_context",
                    content=attachment_context.strip(),
                )
            if selected_ticket_keys:
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=None,
                    agent=self.orchestrator.name,
                    event_type="ticket_context_selected",
                    content=json.dumps(
                        {
                            "selected_ticket_keys": selected_ticket_keys,
                            "loaded_ticket_contexts": [
                                str(item.get("ticket_key") or "")
                                for item in (selected_ticket_contexts or [])
                                if isinstance(item, dict)
                            ],
                        }
                    ),
                )

            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="turn_started",
                content="Orchestrator Agent accepted new user request.",
            )
            if workspace_root:
                bootstrap = ensure_workspace_bootstrap(workspace.root) if workspace.root.exists() and workspace.root.is_dir() else None
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=None,
                    agent=self.orchestrator.name,
                    event_type="workspace_root",
                    content=f"[primary] Workspace root set to {workspace.root}",
                )
                if bootstrap and bootstrap.gitignore_created:
                    add_orchestrator_event(
                        conversation_id=conversation_id,
                        task_id=None,
                        agent=self.orchestrator.name,
                        event_type="workspace_bootstrap",
                        content="Created root .gitignore from the standard template before workflow execution.",
                    )
            if secondary_workspace is not None:
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=None,
                    agent=self.orchestrator.name,
                    event_type="workspace_root",
                    content=f"[secondary] Reference workspace root set to {secondary_workspace.root} (read-only).",
                )

            memory_text = format_memory_text(memory, limit=len(memory))
            selected_workflow_mode = _normalize_workflow_mode(workflow_mode)
            pending_jira_intent = _pending_jira_clarification_intent(workspace.root, conversation_id, user_message)
            resolved_intent = pending_jira_intent or await router.resolve_intent(self, user_message, memory_text)
            normalized_intent = _normalize_orchestrator_intent(resolved_intent)
            intent, workflow_mode_reply = _enforce_workflow_mode(selected_workflow_mode, normalized_intent)
            workflow_payload = {
                "workflow": "codex",
                "intent": normalized_intent.intent,
                "confidence": normalized_intent.confidence,
                "reason": workflow_mode_reply or (intent.reason if intent else normalized_intent.reason),
                "source": intent.source if intent else normalized_intent.source,
                "workflow_mode": selected_workflow_mode,
                "mode_forced": selected_workflow_mode != "auto",
                "blocked": bool(workflow_mode_reply),
            }
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="workflow_selected",
                content=json.dumps(workflow_payload),
            )

            if workflow_mode_reply:
                add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=workflow_mode_reply)
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=None,
                    agent=self.orchestrator.name,
                    event_type="assistant_message",
                    content=workflow_mode_reply,
                )
                add_orchestrator_event(
                    conversation_id=conversation_id,
                    task_id=None,
                    agent=self.orchestrator.name,
                    event_type="turn_completed",
                    content="Turn ended because the selected workflow mode blocked the request.",
                )
                return {
                    "reply": workflow_mode_reply,
                    "tasks": list_orchestrator_tasks(conversation_id),
                    "events": list_orchestrator_events(conversation_id),
                }

            initial_git_hook = await self._run_git_hook(
                conversation_id=conversation_id,
                stage_id="initial",
                workspace_path=str(workspace.root),
                context={
                    "description": user_message[:120],
                    "summary": user_message[:240],
                    "type": "chat",
                },
            )
            self._ensure_git_hook_succeeded(initial_git_hook)

            if intent.intent == "read_only_fs":
                if selected_workflow_mode == "code_review":
                    return await self._run_codex_review_workflow(conversation_id, effective_user_message, workspace)
                return await self._run_read_only_fs_workflow(conversation_id, effective_user_message, workspace)
            if intent.intent == "run_commands":
                return await self._run_run_workflow(conversation_id, effective_user_message, workspace)
            if intent.intent == "research_mcp":
                return await self._run_research_workflow(conversation_id, effective_user_message, memory, workspace)
            if intent.intent == "jira_api":
                return await self._run_jira_workflow(
                    conversation_id,
                    effective_user_message,
                    conversation_memory,
                    workspace,
                    selected_ticket_keys=selected_ticket_keys,
                )
            if intent.intent == "slack_post":
                return await self._run_slack_workflow(conversation_id, effective_user_message, memory)
            if intent.intent == "chat":
                return await self._run_general_workflow(conversation_id, effective_user_message, memory)
            return await self._run_codex_build_workflow(
                conversation_id,
                effective_user_message,
                memory,
                workspace,
                secondary_workspace=secondary_workspace,
                selected_ticket_contexts=selected_ticket_contexts,
            )
        except asyncio.CancelledError:
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="turn_cancelled",
                content="Execution stopped by user request.",
            )
            reply = "Stopped by user request."
            add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=reply)
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="assistant_message",
                content=reply,
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="turn_completed",
                content="Turn ended due to user stop.",
            )
            return {
                "reply": reply,
                "tasks": list_orchestrator_tasks(conversation_id),
                "events": list_orchestrator_events(conversation_id),
            }
        except Exception as exc:
            error_text = self._format_exception(exc)
            self._log_agent_error_event(
                conversation_id=conversation_id,
                task_id=None,
                source_agent=self.orchestrator.agent_id or self.orchestrator.name,
                error=error_text,
                context={"phase": "turn"},
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="turn_error",
                content=error_text,
            )
            reply = f"Sorry — I hit an internal error while processing that request: {error_text}"
            add_message(conversation_id, role="assistant", agent=self.orchestrator.name, content=reply)
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="assistant_message",
                content=reply,
            )
            add_orchestrator_event(
                conversation_id=conversation_id,
                task_id=None,
                agent=self.orchestrator.name,
                event_type="turn_completed",
                content="Turn ended due to error.",
            )
            return {
                "reply": reply,
                "tasks": list_orchestrator_tasks(conversation_id),
                "events": list_orchestrator_events(conversation_id),
            }
        finally:
            self.workspace_context_prefix = ""


__all__ = ["OrchestratorEngine"]
