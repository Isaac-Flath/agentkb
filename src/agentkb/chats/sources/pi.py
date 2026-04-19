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

    match canonical:
        case "Read":
            return {"file_path": arguments.get("path", "")}
        case "Write":
            return {"file_path": arguments.get("path", ""), "content": arguments.get("content", "")}
        case "Edit":
            edits = arguments.get("edits", [])
            if edits:
                first = edits[0]
                return {
                    "file_path": arguments.get("path", ""),
                    "old_string": first.get("oldText", ""),
                    "new_string": first.get("newText", ""),
                }
            return {"file_path": arguments.get("path", "")}
        case "Bash":
            return {"command": arguments.get("command", "")}
        case _:
            return arguments


def _normalize_content_blocks(content: list) -> list:
    """Normalize Pi content blocks to the shared schema."""
    normalized = []
    for block in content:
        match block:
            case str():
                normalized.append(block)
            case dict():
                match block.get("type", ""):
                    case "text":
                        normalized.append({"type": "text", "text": block.get("text", "")})
                    case "thinking":
                        normalized.append({"type": "thinking", "thinking": block.get("thinking", "")})
                    case "toolCall":
                        pi_name = block.get("name", "")
                        canonical = _TOOL_NAME_MAP.get(pi_name, pi_name.capitalize())
                        arguments = block.get("arguments", {})
                        normalized.append({
                            "type": "tool_use",
                            "name": canonical,
                            "input": _normalize_tool_arguments(pi_name, arguments),
                        })
                    case _:
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

            match role:
                case "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = _normalize_content_blocks(content)
                    messages.append({"role": "user", "content": content, "timestamp": timestamp})

                case "assistant":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        content = _normalize_content_blocks(content)
                    if not content:
                        continue  # skip empty streaming stubs
                    messages.append({"role": "assistant", "content": content, "timestamp": timestamp})

                case "toolResult":
                    tool_content = msg.get("content", "")
                    match tool_content:
                        case list():
                            parts = [b.get("text", "") for b in tool_content
                                     if isinstance(b, dict) and b.get("type") == "text"]
                            text = "\n".join(parts)
                        case str():
                            text = tool_content
                        case _:
                            text = ""

                    result_block = {
                        "type": "tool_result",
                        "content": text,
                        "is_error": msg.get("isError", False),
                    }

                    if messages and messages[-1]["role"] == "assistant":
                        prev = messages[-1]["content"]
                        if isinstance(prev, list):
                            prev.append(result_block)
                            continue
                    messages.append({"role": "user", "content": [result_block], "timestamp": timestamp})

    return messages


register(ChatSource(name="pi", source_dir=source_dir, parse_jsonl=parse_jsonl))
