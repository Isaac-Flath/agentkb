"""Claude Code JSONL parser — already in normalized format."""

from __future__ import annotations

import json
from pathlib import Path

from agentkb.chats.sources import ChatSource, register


def source_dir() -> Path | None:
    """Claude Code stores sessions at ~/.claude/projects/."""
    p = Path.home() / ".claude" / "projects"
    return p if p.exists() else None


def parse_jsonl(jsonl_path: Path) -> list[dict]:
    """Parse Claude Code JSONL into normalized messages.

    Claude's format uses top-level ``type`` as the role ("user"/"assistant").
    Content blocks (text, thinking, tool_use, tool_result) are already in
    the normalized schema.
    """
    messages = []
    with open(jsonl_path) as f:
        for line_str in f:
            try:
                obj = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type", "")
            if msg_type not in ("user", "assistant"):
                continue

            msg = obj.get("message", {})
            messages.append({
                "role": msg_type,
                "content": msg.get("content", ""),
                "timestamp": obj.get("timestamp", ""),
            })
    return messages


register(ChatSource(name="claude", source_dir=source_dir, parse_jsonl=parse_jsonl))
