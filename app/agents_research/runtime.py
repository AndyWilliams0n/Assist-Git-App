from __future__ import annotations

import asyncio
import html
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.agent_registry import mark_agent_end, mark_agent_start
from app.agents_shared.runtime import format_memory_text, slugify_text
from app.db import add_message, add_orchestrator_event, list_orchestrator_events, list_orchestrator_tasks
from app.mcp_client import MCPClient, load_mcp_config

RESEARCH_MAX_QUERIES = int(os.getenv("RESEARCH_MAX_QUERIES", "3"))
RESEARCH_SEARCH_RESULT_COUNT = int(os.getenv("RESEARCH_SEARCH_RESULT_COUNT", "5"))
RESEARCH_FETCH_MAX_URLS = int(os.getenv("RESEARCH_FETCH_MAX_URLS", "3"))
RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS = float(os.getenv("RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS", "8"))
RESEARCH_HTTP_FETCH_MAX_CHARS = int(os.getenv("RESEARCH_HTTP_FETCH_MAX_CHARS", "2400"))
RESEARCH_MCP_CALL_TIMEOUT_SECONDS = float(os.getenv("RESEARCH_MCP_CALL_TIMEOUT_SECONDS", "30"))
RESEARCH_MCP_MAX_RETRIES = int(os.getenv("RESEARCH_MCP_MAX_RETRIES", "1"))


def extract_tools_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not payload:
        return []
    tools = payload.get("tools")
    if isinstance(tools, list):
        return [tool for tool in tools if isinstance(tool, dict)]
    return []


def pick_tool_from_list(tools: list[dict[str, Any]], keywords: list[str]) -> str | None:
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
    return scored[0][1]


def pick_fetch_tool_from_list(tools: list[dict[str, Any]]) -> str | None:
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


def extract_search_snippets(payload: dict[str, Any]) -> list[str]:
    snippets: list[str] = []
    text = json.dumps(payload or {})
    for key in ("description", "snippet", "summary"):
        for match in re.finditer(rf'"{key}"\s*:\s*"([^"]+)"', text):
            candidate = html.unescape(match.group(1)).strip()
            if candidate and candidate not in snippets:
                snippets.append(candidate)
    return snippets


def search_results_need_fetch(search_results: list[dict[str, Any]]) -> bool:
    snippets: list[str] = []
    for entry in search_results:
        result = entry.get("result")
        if isinstance(result, dict):
            snippets.extend(extract_search_snippets(result))
    if len(snippets) >= 3:
        return False
    snippet_chars = sum(len(item) for item in snippets)
    return snippet_chars < 500


def user_explicitly_requests_browser(user_message: str) -> bool:
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


def extract_urls(text: str, limit: int = 6) -> list[str]:
    urls = re.findall(r"https?://[^\s\"')>]+", text)
    unique: list[str] = []
    for url in urls:
        if url not in unique:
            unique.append(url)
        if len(unique) >= limit:
            break
    return unique


def build_search_arguments(tool: dict[str, Any], query: str) -> dict[str, Any]:
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


def build_fetch_arguments(tool: dict[str, Any], url: str) -> dict[str, Any]:
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


async def run_mcp_tool_with_retry(
    engine: Any,
    *,
    conversation_id: str,
    workspace: Any,
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
                engine._run_mcp_tool(
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


async def http_fetch_url(url: str) -> dict[str, Any]:
    timeout = httpx.Timeout(
        connect=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
        read=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
        write=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
        pool=RESEARCH_HTTP_FETCH_TIMEOUT_SECONDS,
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AIMultiAgentResearch/1.0; +https://example.local)",
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


async def run_research_workflow(
    engine: Any,
    conversation_id: str,
    user_message: str,
    memory: list[dict[str, str]],
    workspace: Any,
) -> dict[str, object]:
    research_agent_id = engine.research.agent_id
    error_text: str | None = None
    if research_agent_id:
        mark_agent_start(research_agent_id)

    try:
        memory_text = format_memory_text(memory, limit=len(memory))

        query_prompt = (
            f"User request:\n{user_message}\n\n"
            "Propose 1-3 precise web search queries. "
            "Return JSON only as {\"queries\":[\"...\"]}."
        )
        query_output = await engine._call(engine.research, query_prompt, conversation_id=conversation_id)
        query_payload = engine._extract_json(query_output) or {}
        queries = query_payload.get("queries") if isinstance(query_payload.get("queries"), list) else []
        queries = [str(query).strip() for query in queries if str(query).strip()]
        if not queries:
            queries = [user_message.strip()[:180]]
        queries = queries[:RESEARCH_MAX_QUERIES]

        config = load_mcp_config(workspace.root)
        search_results: list[dict[str, Any]] = []
        fetch_results: list[dict[str, Any]] = []
        mcp_warnings: list[str] = []
        mcp_note = ""

        if not config or not config.servers:
            mcp_note = "MCP not configured; no web search results were fetched."
        else:
            client = MCPClient(config)
            search_server = None
            search_tool = None
            tooling = config.tooling.get("search") if config.tooling else None
            if tooling and tooling.get("server") and tooling.get("tool"):
                search_server = tooling["server"]
                search_tool = tooling["tool"]
            else:
                for name in config.servers:
                    if "brave" in name.lower() or "search" in name.lower():
                        search_server = name
                        break
                if not search_server:
                    search_server = next(iter(config.servers.keys()))
                try:
                    tools_payload = await asyncio.to_thread(client.list_tools, search_server)
                    tools = extract_tools_list(tools_payload)
                    search_tool = pick_tool_from_list(tools, ["search", "brave"])
                except Exception as exc:
                    mcp_warnings.append(
                        f"Search server tool discovery failed for '{search_server}': {engine._format_exception(exc)}"
                    )

            if search_server and search_tool:
                try:
                    tools_payload = await asyncio.to_thread(client.list_tools, search_server)
                    tools = extract_tools_list(tools_payload)
                    tool_lookup = {tool.get("name"): tool for tool in tools if isinstance(tool, dict)}
                    for query in queries:
                        tool_schema = tool_lookup.get(search_tool, {"name": search_tool})
                        args = build_search_arguments(tool_schema, query)
                        try:
                            result = await run_mcp_tool_with_retry(
                                engine,
                                conversation_id=conversation_id,
                                workspace=workspace,
                                server_name=search_server,
                                tool_name=search_tool,
                                arguments=args,
                                agent_name=engine.research.name,
                            )
                            search_results.append({"query": query, "result": result})
                        except Exception as exc:
                            mcp_warnings.append(
                                f"Search call failed for query '{query[:80]}': {engine._format_exception(exc)}"
                            )
                except Exception as exc:
                    mcp_warnings.append(
                        f"Search tool resolution failed for '{search_server}': {engine._format_exception(exc)}"
                    )
            else:
                mcp_note = "MCP search tool not found; skipping web search."

            should_fetch = search_results_need_fetch(search_results)
            if should_fetch and search_results:
                candidate_urls: list[str] = []
                for entry in search_results:
                    urls = extract_urls(json.dumps(entry.get("result", {})), limit=4)
                    for url in urls:
                        if url not in candidate_urls:
                            candidate_urls.append(url)
                        if len(candidate_urls) >= RESEARCH_FETCH_MAX_URLS:
                            break
                    if len(candidate_urls) >= RESEARCH_FETCH_MAX_URLS:
                        break

                if candidate_urls:
                    for url in candidate_urls:
                        try:
                            http_result = await http_fetch_url(url)
                            fetch_results.append({"url": url, "result": http_result, "source": "http"})
                        except Exception as exc:
                            mcp_warnings.append(
                                f"HTTP fetch failed for URL '{url[:120]}': {engine._format_exception(exc)}"
                            )

                auth_required = any(
                    bool(item.get("result", {}).get("auth_required"))
                    for item in fetch_results
                    if isinstance(item.get("result"), dict)
                )
                allow_browser_fallback = user_explicitly_requests_browser(user_message) or auth_required

                browser_server = None
                browser_tool = None
                tooling_fetch = config.tooling.get("fetch") if config.tooling else None
                if allow_browser_fallback:
                    if tooling_fetch and tooling_fetch.get("server"):
                        browser_server = tooling_fetch["server"]
                        browser_tool = tooling_fetch.get("tool")
                    else:
                        for name in config.servers:
                            if "browser" in name.lower() or "playwright" in name.lower():
                                browser_server = name
                                break

                if browser_server and not browser_tool:
                    try:
                        tools_payload = await asyncio.to_thread(client.list_tools, browser_server)
                        tools = extract_tools_list(tools_payload)
                        browser_tool = pick_fetch_tool_from_list(tools)
                    except Exception as exc:
                        mcp_warnings.append(
                            f"Fetch server tool discovery failed for '{browser_server}': {engine._format_exception(exc)}"
                        )

                if browser_server and browser_tool and (not fetch_results or auth_required):
                    try:
                        tools_payload = await asyncio.to_thread(client.list_tools, browser_server)
                        tools = extract_tools_list(tools_payload)
                        tool_lookup = {tool.get("name"): tool for tool in tools if isinstance(tool, dict)}
                        for url in candidate_urls[:1]:
                            tool_schema = tool_lookup.get(browser_tool, {"name": browser_tool})
                            args = build_fetch_arguments(tool_schema, url)
                            try:
                                result = await run_mcp_tool_with_retry(
                                    engine,
                                    conversation_id=conversation_id,
                                    workspace=workspace,
                                    server_name=browser_server,
                                    tool_name=browser_tool,
                                    arguments=args,
                                    agent_name=engine.research.name,
                                )
                                fetch_results.append({"url": url, "result": result, "source": "browser"})
                            except Exception as exc:
                                mcp_warnings.append(
                                    f"Fetch call failed for URL '{url[:120]}': {engine._format_exception(exc)}"
                                )
                    except Exception as exc:
                        mcp_warnings.append(
                            f"Fetch tool resolution failed for '{browser_server}': {engine._format_exception(exc)}"
                        )
            elif search_results:
                mcp_note = "Search snippets were sufficient; skipped page fetch for reliability."

        if mcp_warnings and not mcp_note:
            mcp_note = "MCP web tooling encountered errors; partial or no results were fetched."

        research_prompt = (
            f"User request:\n{user_message}\n\n"
            f"Recent memory:\n{memory_text or '(none)'}\n\n"
            f"Queries:\n{json.dumps(queries, indent=2)}\n\n"
            f"MCP note:\n{mcp_note}\n\n"
            f"MCP warnings:\n{json.dumps(mcp_warnings, indent=2)}\n\n"
            f"Search results:\n{json.dumps(search_results, indent=2)[:6000]}\n\n"
            f"Fetched pages:\n{json.dumps(fetch_results, indent=2)[:6000]}\n\n"
            "Synthesize into a concise markdown report with citations and a Sources section. "
            "Prefer evidence from search snippets first; include fetched-page evidence only if it adds material facts. "
            "Keep the summary compact and explicit about missing/failed fetches. "
            "If MCP data is missing, unavailable, or empty, say that explicitly and do not invent sources."
        )
        final_markdown = await engine._call(engine.research, research_prompt, conversation_id=conversation_id)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = slugify_text(user_message)
        relative_path = f".assist/research/{date_str}-{slug}.md"
        workspace.mkdir(".assist/research")
        engine._write_workspace_file(conversation_id, None, workspace, relative_path, final_markdown)

        final_prompt = (
            f"User request:\n{user_message}\n\n"
            f"Research summary saved to {relative_path}.\n\n"
            f"Summary:\n{final_markdown[:2000]}\n\n"
            "Respond as Orchestrator Agent with what was done, what changed, and next steps."
        )
        final_reply = await engine._call(engine.orchestrator, final_prompt, conversation_id=conversation_id)
        add_message(conversation_id, role="assistant", agent=engine.orchestrator.name, content=final_reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type="assistant_message",
            content=final_reply,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )
        return {
            "reply": final_reply,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }
    except Exception as exc:
        error_text = engine._format_exception(exc)
        raise
    finally:
        if research_agent_id:
            mark_agent_end(research_agent_id, error_text)


__all__ = [
    "build_fetch_arguments",
    "build_search_arguments",
    "extract_search_snippets",
    "extract_tools_list",
    "extract_urls",
    "http_fetch_url",
    "pick_fetch_tool_from_list",
    "pick_tool_from_list",
    "run_mcp_tool_with_retry",
    "run_research_workflow",
    "search_results_need_fetch",
    "user_explicitly_requests_browser",
]
