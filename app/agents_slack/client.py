from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

import httpx

SLACK_API_BASE = "https://slack.com/api"


class SlackClient:
    def __init__(
        self,
        bot_token: str | None = None,
        signing_secret: str | None = None,
    ) -> None:
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.signing_secret = signing_secret or os.getenv("SLACK_SIGNING_SECRET", "")

    def is_configured(self) -> bool:
        return bool(self.bot_token)

    async def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        if not self.bot_token:
            raise RuntimeError(
                "SLACK_BOT_TOKEN is not set. Configure it in your environment."
            )
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{SLACK_API_BASE}/chat.postMessage",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
            return data

    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        if not self.signing_secret:
            return False
        try:
            if abs(time.time() - float(timestamp)) > 300:
                return False
        except ValueError:
            return False
        base = f"v0:{timestamp}:".encode() + body
        expected = "v0=" + hmac.new(
            self.signing_secret.encode(),
            base,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
