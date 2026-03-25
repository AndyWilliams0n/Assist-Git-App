from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.mcp_client import MCPClient, MCPConfig, load_mcp_config

ASSIST_BRAIN_DEFAULT_SERVER = "assist-brain"
ASSIST_BRAIN_DEFAULT_SEARCH_TOOL = "search_thoughts"
ASSIST_BRAIN_DEFAULT_CAPTURE_TOOL = "capture_thought"
ASSIST_BRAIN_MAX_SEARCH_CHARS = int(os.getenv("ASSIST_BRAIN_MAX_SEARCH_CHARS", "4000"))


def assist_brain_enabled() -> bool:
    value = str(os.getenv("ASSIST_BRAIN_MEMORY_ENABLED", "true")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _resolve_server_name(config: MCPConfig) -> str:
    preferred = str(os.getenv("ASSIST_BRAIN_SERVER_NAME", ASSIST_BRAIN_DEFAULT_SERVER)).strip()
    if preferred and preferred in config.servers:
        return preferred

    tooling = config.tooling.get("memory") if config.tooling else None
    configured = str(tooling.get("server") or "").strip() if isinstance(tooling, dict) else ""
    if configured and configured in config.servers:
        return configured

    for name in config.servers:
        lowered = name.lower()
        if "assist" in lowered and "brain" in lowered:
            return name
    return ""


def _resolve_memory_tool_names(config: MCPConfig, kind: str) -> list[str]:
    tooling = config.tooling.get("memory") if config.tooling else None
    configured = ""
    if isinstance(tooling, dict):
        configured = str(tooling.get(f"{kind}_tool") or "").strip()

    if kind == "search":
        defaults = [ASSIST_BRAIN_DEFAULT_SEARCH_TOOL, "searchThoughts"]
    else:
        defaults = [ASSIST_BRAIN_DEFAULT_CAPTURE_TOOL, "captureThought"]

    names: list[str] = []
    if configured:
        names.append(configured)
    names.extend(defaults)
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(name)
    return deduped


def _extract_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(tools, list):
        return []
    return [item for item in tools if isinstance(item, dict)]


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or "").strip()


def _find_tool(tools: list[dict[str, Any]], names: list[str]) -> dict[str, Any] | None:
    normalized = {name.lower() for name in names if str(name).strip()}
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        if name.lower() in normalized:
            return tool
    for tool in tools:
        description = str(tool.get("description") or "").lower()
        if any(name.replace("_", " ") in description for name in normalized):
            return tool
    return None


def _tool_properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") if isinstance(tool, dict) else None
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    return properties


def _resolve_property_name(properties: dict[str, Any], preferred_keys: list[str]) -> str | None:
    if not properties:
        return None
    lookup = {str(key).lower(): str(key) for key in properties}
    for key in preferred_keys:
        actual = lookup.get(str(key).lower())
        if actual:
            return actual
    return None


def _build_search_arguments(tool: dict[str, Any], query: str, limit: int) -> dict[str, Any]:
    properties = _tool_properties(tool)
    if not properties:
        return {"query": query, "limit": limit}

    args: dict[str, Any] = {}
    query_key = _resolve_property_name(properties, ["query", "q", "text", "input", "search"])
    if query_key:
        args[query_key] = query
    else:
        args["query"] = query

    limit_key = _resolve_property_name(properties, ["limit", "top_k", "k", "count", "max_results"])
    if limit_key:
        args[limit_key] = max(1, int(limit))
    return args


def _build_capture_arguments(
    tool: dict[str, Any],
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    properties = _tool_properties(tool)
    if not properties:
        args: dict[str, Any] = {"content": content}
        if metadata:
            args["metadata"] = metadata
        return args

    args = {}
    content_key = _resolve_property_name(properties, ["content", "text", "input", "thought", "note"])
    if content_key:
        args[content_key] = content
    else:
        args["content"] = content

    metadata_key = _resolve_property_name(properties, ["metadata", "meta", "context"])
    if metadata_key and metadata:
        args[metadata_key] = metadata

    timestamp_key = _resolve_property_name(properties, ["timestamp", "created_at", "createdAt"])
    if timestamp_key and timestamp_key not in args:
        args[timestamp_key] = datetime.now(timezone.utc).isoformat()

    return args


def _result_preview(payload: dict[str, Any], *, max_chars: int = ASSIST_BRAIN_MAX_SEARCH_CHARS) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str) and str(item.get("text")).strip():
                chunks.append(str(item["text"]).strip())
                continue
            if isinstance(item.get("content"), str) and str(item.get("content")).strip():
                chunks.append(str(item["content"]).strip())
                continue
            if isinstance(item.get("data"), dict):
                chunks.append(json.dumps(item["data"], ensure_ascii=False))
        if chunks:
            return "\n".join(chunks)[:max_chars]

    for key in ("text", "summary", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:max_chars]

    return json.dumps(payload, ensure_ascii=False)[:max_chars]


def _resolve_client(workspace_root: str | Path | None) -> tuple[MCPClient, MCPConfig, str] | None:
    if not assist_brain_enabled():
        return None

    config = load_mcp_config(workspace_root)
    if not config or not config.servers:
        return None

    server_name = _resolve_server_name(config)
    if not server_name:
        return None

    server = config.servers.get(server_name)
    if not server:
        return None
    if server.transport == "http":
        headers = {str(key).lower(): str(value) for key, value in (server.headers or {}).items()}
        access_key = str(headers.get("x-brain-key") or "").strip()
        if not access_key:
            return None

    return MCPClient(config), config, server_name


def search_assist_brain_sync(
    workspace_root: str | Path | None,
    *,
    query: str,
    limit: int = 5,
) -> str:
    resolved = _resolve_client(workspace_root)
    if not resolved:
        return ""

    client, config, server_name = resolved
    tools = _extract_tools(client.list_tools(server_name))
    search_tool = _find_tool(tools, _resolve_memory_tool_names(config, "search"))
    if not search_tool:
        return ""

    tool_name = _tool_name(search_tool)
    if not tool_name:
        return ""

    arguments = _build_search_arguments(search_tool, str(query).strip(), int(limit))
    result = client.call_tool(server_name, tool_name, arguments)
    return _result_preview(result)


def capture_assist_brain_sync(
    workspace_root: str | Path | None,
    *,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    resolved = _resolve_client(workspace_root)
    if not resolved:
        return False

    text = str(content or "").strip()
    if not text:
        return False

    client, config, server_name = resolved
    tools = _extract_tools(client.list_tools(server_name))
    capture_tool = _find_tool(tools, _resolve_memory_tool_names(config, "capture"))
    if not capture_tool:
        return False

    tool_name = _tool_name(capture_tool)
    if not tool_name:
        return False

    arguments = _build_capture_arguments(capture_tool, text, metadata)
    client.call_tool(server_name, tool_name, arguments)
    return True


async def search_assist_brain(
    workspace_root: str | Path | None,
    *,
    query: str,
    limit: int = 5,
) -> str:
    try:
        return await asyncio.to_thread(
            search_assist_brain_sync,
            workspace_root,
            query=query,
            limit=limit,
        )
    except Exception:
        return ""


async def capture_assist_brain(
    workspace_root: str | Path | None,
    *,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    try:
        return await asyncio.to_thread(
            capture_assist_brain_sync,
            workspace_root,
            content=content,
            metadata=metadata,
        )
    except Exception:
        return False


__all__ = [
    "assist_brain_enabled",
    "capture_assist_brain",
    "capture_assist_brain_sync",
    "search_assist_brain",
    "search_assist_brain_sync",
]
