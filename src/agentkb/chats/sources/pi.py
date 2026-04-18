"""Pi (pi.dev) JSONL parser — normalize to Claude Code's block format."""

from __future__ import annotations

import json
from pathlib import Path

from agentkb.chats.sources import ChatSource, register


def source_dir() -> Path | None:
    """Pi stores sessions at ~/.pi/agent/sessions/."""
    p = Path.home() / ".pi" / "agent" / "sessions"
    return p if p.exists() else None


# Pi uses lowercase tool names; map to capitalized canonical names.
_TOOL_NAME_MAP = {
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "bash": "Bash",
    "list_dir": "Glob",
}


def _normalize_tool_arguments(tool_name: str, arguments: dict) -> dict:
    """Convert Pi tool argument fields to Claude's normalized schema."""
    canonical = _TOOL_NAME_MAP.get(tool_name, tool_name.capitalize())

    if canonical == "Read":
        return {"file_path": arguments.get("path", "")}
    if canonical == "Write":
        return {"file_path": arguments.get("path", ""), "content": arguments.get("content", "")}
    if canonical == "Edit":
        edits = arguments.get("edits", [])
        if edits:
            first = edits[0]
            return {
                "file_path": arguments.get("path", ""),
                "old_string": first.get("oldText", ""),
                "new_string": first.get("newText", ""),
            }
        return {"file_path": arguments.get("path", "")}
    if canonical == "Bash":
        return {"command": arguments.get("command", "")}
    # Unknown tool — pass through as-is
    return arguments


def _normalize_content_blocks(content: list) -> list:
    """Normalize Pi content blocks to the shared schema."""
    normalized = []
    for block in content:
        if isinstance(block, str):
            normalized.append(block)
        elif isinstance(block, dict):
            bt = block.get("type", "")
            if bt == "text":
                normalized.append({"type": "text", "text": block.get("text", "")})
            elif bt == "thinking":
                normalized.append({"type": "thinking", "thinking": block.get("thinking", "")})
            elif bt == "toolCall":
                pi_name = block.get("name", "")
                canonical = _TOOL_NAME_MAP.get(pi_name, pi_name.capitalize())
                arguments = block.get("arguments", {})
                normalized.append({
                    "type": "tool_use",
                    "name": canonical,
                    "input": _normalize_tool_arguments(pi_name, arguments),
                })
            else:
                normalized.append(block)
    return normalized


def parse_jsonl(jsonl_path: Path) -> list[dict]:
    """Parse Pi JSONL into normalized messages.

    Pi uses ``type: "message"`` with ``message.role`` for the role.
    Tool results are separate ``toolResult`` messages — we append them
    as ``tool_result`` blocks on the preceding assistant message.
    """
    messages: list[dict] = []
    with open(jsonl_path) as f:
        for line_str in f:
            try:
                obj = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "message":
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")
            timestamp = obj.get("timestamp", "")

            if role == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = _normalize_content_blocks(content)
                messages.append({"role": "user", "content": content, "timestamp": timestamp})

            elif role == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    content = _normalize_content_blocks(content)
                if not content:
                    continue  # skip empty streaming stubs
                messages.append({"role": "assistant", "content": content, "timestamp": timestamp})

            elif role == "toolResult":
                # Extract text from the tool result content
                tool_content = msg.get("content", "")
                if isinstance(tool_content, list):
                    parts = [b.get("text", "") for b in tool_content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    text = "\n".join(parts)
                elif isinstance(tool_content, str):
                    text = tool_content
                else:
                    text = ""

                result_block = {
                    "type": "tool_result",
                    "content": text,
                    "is_error": msg.get("isError", False),
                }

                # Append to the preceding assistant message
                if messages and messages[-1]["role"] == "assistant":
                    prev = messages[-1]["content"]
                    if isinstance(prev, list):
                        prev.append(result_block)
                        continue
                # Fallback: emit as a synthetic user message
                messages.append({"role": "user", "content": [result_block], "timestamp": timestamp})

    return messages


register(ChatSource(name="pi", source_dir=source_dir, parse_jsonl=parse_jsonl))
