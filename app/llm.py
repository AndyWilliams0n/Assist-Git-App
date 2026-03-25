from __future__ import annotations

import asyncio
import base64
import json
import os
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.settings_store import get_llm_provider_settings


def _provider_model(provider: str, env_key: str, fallback: str) -> str:
    configured = str(get_llm_provider_settings(provider).get("model") or "").strip()
    if configured:
        return configured
    return str(os.getenv(env_key, fallback)).strip() or fallback


def _provider_int_setting(provider: str, key: str, env_key: str, fallback: int) -> int:
    configured = get_llm_provider_settings(provider).get(key)
    if isinstance(configured, bool):
        return fallback
    if isinstance(configured, int):
        return configured
    if isinstance(configured, float):
        return int(configured)
    if isinstance(configured, str):
        try:
            return int(configured.strip())
        except Exception:
            pass
    try:
        return int(os.getenv(env_key, str(fallback)))
    except Exception:
        return fallback


@dataclass
class LLMConfig:
    openai_model: str = field(default_factory=lambda: _provider_model("openai", "OPENAI_MODEL", "gpt-4.1-mini"))
    anthropic_model: str = field(
        default_factory=lambda: _provider_model("anthropic", "ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    )
    anthropic_max_tokens: int = field(
        default_factory=lambda: _provider_int_setting("anthropic", "max_tokens", "ANTHROPIC_MAX_TOKENS", 4000)
    )
    timeout_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "45")))
    retry_max_attempts: int = field(default_factory=lambda: int(os.getenv("LLM_RETRIES", "2")))
    retry_backoff_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "1.0")))
    retry_max_backoff_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_RETRY_MAX_BACKOFF_SECONDS", "8.0")))
    retry_jitter_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_RETRY_JITTER_SECONDS", "0.25")))


class LLMClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")

    @staticmethod
    def _error_text(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            try:
                data = response.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                if isinstance(data.get("error"), dict) and data["error"].get("message"):
                    return str(data["error"]["message"])
                if data.get("error"):
                    return str(data["error"])
            return f"HTTP {response.status_code}"
        text = str(exc).strip()
        if text:
            return text
        return type(exc).__name__

    def _should_retry(self, exc: Exception) -> tuple[bool, float | None]:
        if isinstance(exc, httpx.TimeoutException):
            return True, None
        if isinstance(exc, httpx.NetworkError):
            return True, None
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            status = response.status_code if response else None
            if status in {408, 429, 500, 502, 503, 504}:
                retry_after = response.headers.get("Retry-After") if response else None
                if retry_after:
                    try:
                        return True, float(retry_after)
                    except ValueError:
                        return True, None
                return True, None
        return False, None

    async def _sleep_backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            await asyncio.sleep(max(0.0, retry_after))
            return
        base = self.config.retry_backoff_seconds * (2 ** max(0, attempt))
        base = min(self.config.retry_max_backoff_seconds, base)
        jitter = random.random() * self.config.retry_jitter_seconds
        await asyncio.sleep(base + jitter)

    async def openai_health(self) -> dict[str, Any]:
        if not self.openai_api_key:
            return {
                "provider": "openai",
                "configured": False,
                "reachable": False,
                "model": self.config.openai_model,
                "error": "OPENAI_API_KEY is not set",
            }

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get("https://api.openai.com/v1/models", headers=headers)
                response.raise_for_status()
            return {
                "provider": "openai",
                "configured": True,
                "reachable": True,
                "model": self.config.openai_model,
                "error": "",
            }
        except Exception as exc:
            return {
                "provider": "openai",
                "configured": True,
                "reachable": False,
                "model": self.config.openai_model,
                "error": self._error_text(exc),
            }

    async def anthropic_health(self) -> dict[str, Any]:
        if not self.anthropic_api_key:
            return {
                "provider": "anthropic",
                "configured": False,
                "reachable": False,
                "model": self.config.anthropic_model,
                "error": "ANTHROPIC_API_KEY is not set",
            }

        headers = {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get("https://api.anthropic.com/v1/models", headers=headers)
                response.raise_for_status()
            return {
                "provider": "anthropic",
                "configured": True,
                "reachable": True,
                "model": self.config.anthropic_model,
                "error": "",
            }
        except Exception as exc:
            return {
                "provider": "anthropic",
                "configured": True,
                "reachable": False,
                "model": self.config.anthropic_model,
                "error": self._error_text(exc),
            }

    async def providers_health(self) -> dict[str, Any]:
        openai = await self.openai_health()
        anthropic = await self.anthropic_health()
        overall = "ok" if openai["reachable"] and anthropic["reachable"] else "degraded"
        return {
            "status": overall,
            "openai": openai,
            "anthropic": anthropic,
        }

    async def _openai_v1_responses(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        payload = {
            "model": model or self.config.openai_model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        text = data.get("output_text", "").strip()
        if text:
            return text

        outputs = data.get("output", [])
        chunks: list[str] = []
        for item in outputs:
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        return "\n".join(chunks).strip() or "No response content returned by OpenAI."

    async def _openai_chat_completions(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        payload = {
            "model": model or self.config.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return "No response content returned by OpenAI."

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip() or "No response content returned by OpenAI."

        if isinstance(content, list):
            chunks = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")]
            return "\n".join(chunks).strip() or "No response content returned by OpenAI."

        return "No response content returned by OpenAI."

    async def openai_response(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        last_exc: Exception | None = None
        for attempt in range(self.config.retry_max_attempts + 1):
            try:
                return await self._openai_v1_responses(system_prompt, user_prompt, model=model)
            except httpx.HTTPStatusError as exc:
                # Some model/account combos reject the Responses payload shape; fallback to Chat Completions.
                if exc.response.status_code in {400, 404, 415, 422}:
                    try:
                        return await self._openai_chat_completions(system_prompt, user_prompt, model=model)
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            "OpenAI request failed on both endpoints: "
                            f"responses=({self._error_text(exc)}); "
                            f"chat_completions=({self._error_text(fallback_exc)})"
                        ) from fallback_exc
                last_exc = exc
                should_retry, retry_after = self._should_retry(exc)
                if attempt >= self.config.retry_max_attempts or not should_retry:
                    raise RuntimeError(self._error_text(exc)) from exc
                await self._sleep_backoff(attempt, retry_after)
            except Exception as exc:
                last_exc = exc
                should_retry, retry_after = self._should_retry(exc)
                if attempt >= self.config.retry_max_attempts or not should_retry:
                    raise RuntimeError(self._error_text(exc)) from exc
                await self._sleep_backoff(attempt, retry_after)
        raise RuntimeError(self._error_text(last_exc or RuntimeError("Unknown LLM error")))

    async def anthropic_messages(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        payload: dict[str, Any] = {
            "model": model or self.config.anthropic_model,
            "max_tokens": max_tokens or self.config.anthropic_max_tokens,
            "system": system_prompt,
            "messages": messages,
            "temperature": 0.3 if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self.config.retry_max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                last_exc = exc
                should_retry, retry_after = self._should_retry(exc)
                if attempt >= self.config.retry_max_attempts or not should_retry:
                    raise RuntimeError(self._error_text(exc)) from exc
                await self._sleep_backoff(attempt, retry_after)
        raise RuntimeError(self._error_text(last_exc or RuntimeError("Unknown LLM error")))

    async def anthropic_response(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        data = await self.anthropic_messages(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            model=model,
            max_tokens=max_tokens,
        )
        text_parts = [part.get("text", "") for part in data.get("content", []) if part.get("type") == "text"]
        text = "\n".join(part for part in text_parts if part).strip()
        return text or "No response content returned by Anthropic."

    async def openai_messages_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        def _normalize_messages_for_chat(raw_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
            converted: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
            for message in raw_messages:
                role = str(message.get("role") or "").strip().lower()
                content = message.get("content")
                if role == "user" and isinstance(content, str):
                    converted.append({"role": "user", "content": content})
                    continue
                if isinstance(content, list):
                    if role == "assistant":
                        text_chunks: list[str] = []
                        tool_calls: list[dict[str, Any]] = []
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            block_type = str(block.get("type") or "")
                            if block_type == "text":
                                text = str(block.get("text") or "")
                                if text:
                                    text_chunks.append(text)
                            elif block_type == "tool_use":
                                call_id = str(block.get("id") or "")
                                name = str(block.get("name") or "")
                                tool_input = block.get("input")
                                if not isinstance(tool_input, dict):
                                    tool_input = {}
                                if call_id and name:
                                    tool_calls.append(
                                        {
                                            "id": call_id,
                                            "type": "function",
                                            "function": {
                                                "name": name,
                                                "arguments": json.dumps(tool_input),
                                            },
                                        }
                                    )
                        if text_chunks or tool_calls:
                            converted.append(
                                {
                                    "role": "assistant",
                                    "content": "\n".join(text_chunks).strip(),
                                    **({"tool_calls": tool_calls} if tool_calls else {}),
                                }
                            )
                        continue
                    if role == "user":
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            block_type = str(block.get("type") or "")
                            if block_type == "tool_result":
                                call_id = str(block.get("tool_use_id") or "")
                                text = str(block.get("content") or "")
                                if call_id:
                                    converted.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": call_id,
                                            "content": text,
                                        }
                                    )
                else:
                    if role in {"user", "assistant", "tool"}:
                        converted.append({"role": role, "content": str(content or "")})
            return converted

        openai_tools: list[dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            schema = tool.get("input_schema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(tool.get("description") or ""),
                        "parameters": schema,
                    },
                }
            )

        payload: dict[str, Any] = {
            "model": model or self.config.openai_model,
            "messages": _normalize_messages_for_chat(messages),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if openai_tools:
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self.config.retry_max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    return {"content": [{"type": "text", "text": "No response content returned by OpenAI."}]}
                message = choices[0].get("message") if isinstance(choices[0], dict) else {}
                if not isinstance(message, dict):
                    message = {}

                normalized_content: list[dict[str, Any]] = []
                text = message.get("content")
                if isinstance(text, str) and text.strip():
                    normalized_content.append({"type": "text", "text": text.strip()})
                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        call_id = str(call.get("id") or "").strip()
                        fn = call.get("function")
                        if not isinstance(fn, dict):
                            continue
                        name = str(fn.get("name") or "").strip()
                        args_raw = fn.get("arguments")
                        parsed_args: dict[str, Any] = {}
                        if isinstance(args_raw, str) and args_raw.strip():
                            try:
                                maybe_dict = json.loads(args_raw)
                                if isinstance(maybe_dict, dict):
                                    parsed_args = maybe_dict
                            except Exception:
                                parsed_args = {}
                        if call_id and name:
                            normalized_content.append(
                                {
                                    "type": "tool_use",
                                    "id": call_id,
                                    "name": name,
                                    "input": parsed_args,
                                }
                            )
                if not normalized_content:
                    normalized_content.append({"type": "text", "text": "No response content returned by OpenAI."})
                return {"content": normalized_content}
            except Exception as exc:
                last_exc = exc
                should_retry, retry_after = self._should_retry(exc)
                if attempt >= self.config.retry_max_attempts or not should_retry:
                    raise RuntimeError(self._error_text(exc)) from exc
                await self._sleep_backoff(attempt, retry_after)
        raise RuntimeError(self._error_text(last_exc or RuntimeError("Unknown LLM error")))

    async def openai_vision_response(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model: str | None = None,
    ) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if not image_bytes:
            raise RuntimeError("Image payload is empty")

        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"
        payload: dict[str, Any] = {
            "model": model or self.config.openai_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self.config.retry_max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                choices = data.get("choices", [])
                if not choices:
                    return "No response content returned by OpenAI."

                message = choices[0].get("message", {})
                content = message.get("content", "")
                if isinstance(content, str):
                    return content.strip() or "No response content returned by OpenAI."
                if isinstance(content, list):
                    chunks = [
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") in {"text", "output_text"} and part.get("text")
                    ]
                    return "\n".join(chunks).strip() or "No response content returned by OpenAI."
                return "No response content returned by OpenAI."
            except Exception as exc:
                last_exc = exc
                should_retry, retry_after = self._should_retry(exc)
                if attempt >= self.config.retry_max_attempts or not should_retry:
                    raise RuntimeError(self._error_text(exc)) from exc
                await self._sleep_backoff(attempt, retry_after)
        raise RuntimeError(self._error_text(last_exc or RuntimeError("Unknown LLM error")))
