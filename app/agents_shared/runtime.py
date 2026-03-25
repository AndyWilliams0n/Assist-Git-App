from __future__ import annotations

import re


def format_memory_text(memory: list[dict[str, str]], limit: int = 8) -> str:
    return "\n".join(
        f"- {message['role']}[{message.get('agent', '')}]: {message['content']}"
        for message in memory[-max(0, limit) :]
    )


def slugify_text(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    if not words:
        return "note"
    return "-".join(words[:max_words])[:60]


__all__ = ["format_memory_text", "slugify_text"]
