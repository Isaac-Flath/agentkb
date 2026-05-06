"""Codex CLI rollout parser."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agentkb.chats.sources import ChatSource, register


def source_dir() -> Path | None:
    """Codex stores session rollouts under ~/.codex/sessions/."""
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    p = codex_home / "sessions"
    return p if p.exists() else None


def project_name(jsonl_path: Path, _rel_path: str) -> str:
    """Use the rollout cwd as the project label when Codex recorded one."""
    meta = _session_meta(jsonl_path)
    cwd = meta.get("cwd", "")
    if cwd:
        name = Path(cwd).name
        if name:
            return name

    parent = jsonl_path.parent
    if len(parent.parts) >= 3:
        return "-".join(parent.parts[-3:])
    return parent.name or "codex"


def parse_jsonl(jsonl_path: Path) -> list[dict]:
    """Parse Codex JSONL into normalized user/assistant messages.

    Codex rollouts are event streams. The user prompt is recorded as an
    ``event_msg/user_message``; assistant text and tool calls are recorded as
    ``response_item`` rows.
    """
    messages: list[dict] = []
    saw_event_user_message = False

    with open(jsonl_path) as f:
        for line_str in f:
            try:
                obj = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            timestamp = obj.get("timestamp", "")
            row_type = obj.get("type", "")
            payload = obj.get("payload", {})
            if not isinstance(payload, dict):
                continue

            if row_type == "event_msg":
                if payload.get("type") == "user_message":
                    text = payload.get("message", "")
                    if isinstance(text, str) and text.strip():
                        if not saw_event_user_message:
                            messages = [
                                msg for msg in messages
                                if not msg.get("_codex_fallback_user")
                            ]
                            saw_event_user_message = True
                        messages.append({
                            "role": "user",
                            "content": text,
                            "timestamp": timestamp,
                        })
                continue

            if row_type != "response_item":
                continue

            item_type = payload.get("type", "")
            match item_type:
                case "message":
                    role = payload.get("role", "")
                    if role == "user":
                        if saw_event_user_message:
                            continue
                        blocks = _message_blocks(payload.get("content", []))
                        if blocks:
                            messages.append({
                                "role": "user",
                                "content": blocks,
                                "timestamp": timestamp,
                                "_codex_fallback_user": True,
                            })
                        continue
                    if role != "assistant":
                        # Developer messages include prompt scaffolding/context.
                        continue
                    blocks = _message_blocks(payload.get("content", []))
                    if blocks:
                        messages.append({
                            "role": "assistant",
                            "content": blocks,
                            "timestamp": timestamp,
                        })

                case "function_call" | "custom_tool_call" | "tool_search_call" | "web_search_call":
                    _append_assistant_block(messages, _tool_use_block(payload), timestamp)

                case "function_call_output" | "custom_tool_call_output" | "tool_search_output":
                    _append_assistant_block(messages, _tool_result_block(payload), timestamp)

    for msg in messages:
        msg.pop("_codex_fallback_user", None)
    return messages


def _session_meta(jsonl_path: Path) -> dict:
    with open(jsonl_path) as f:
        for line_str in f:
            try:
                obj = json.loads(line_str)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "session_meta":
                continue
            payload = obj.get("payload", {})
            return payload if isinstance(payload, dict) else {}
    return {}


def _message_blocks(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []

    blocks = []
    for item in content:
        if not isinstance(item, dict):
            continue
        match item.get("type", ""):
            case "input_text" | "output_text" | "text":
                text = item.get("text", "")
                if text.strip():
                    blocks.append({"type": "text", "text": text})
            case "input_image":
                blocks.append({"type": "text", "text": "[image]"})
    return blocks


def _tool_use_block(payload: dict) -> dict:
    item_type = payload.get("type", "")
    if item_type == "web_search_call":
        name = "web_search"
        tool_input = payload.get("action", {})
    else:
        name = payload.get("name") or item_type
        tool_input = payload.get("arguments", payload.get("input", {}))

    if item_type in ("function_call", "tool_search_call"):
        tool_input = _decode_json_arguments(tool_input)

    return {
        "type": "tool_use",
        "name": name,
        "input": tool_input,
    }


def _tool_result_block(payload: dict) -> dict:
    output = payload.get("output", "")
    if output == "" and "tools" in payload:
        output = json.dumps(payload.get("tools", []), indent=2)

    return {
        "type": "tool_result",
        "content": output,
        "is_error": payload.get("status") == "failed",
    }


def _decode_json_arguments(value):
    if not isinstance(value, str):
        return value
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"arguments": value}
    return decoded if isinstance(decoded, dict) else {"arguments": decoded}


def _append_assistant_block(messages: list[dict], block: dict, timestamp: str) -> None:
    if messages and messages[-1].get("role") == "assistant":
        content = messages[-1].setdefault("content", [])
        if isinstance(content, list):
            content.append(block)
            return

    messages.append({
        "role": "assistant",
        "content": [block],
        "timestamp": timestamp,
    })


register(ChatSource(
    name="codex",
    source_dir=source_dir,
    parse_jsonl=parse_jsonl,
    project_name=project_name,
))
