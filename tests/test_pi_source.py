"""Tests for Pi JSONL parsing and normalization.

Pi stores sessions as JSONL with a different structure than Claude Code:
- Entry-level type is "message" with role inside (not the role at top level)
- Tool calls use "toolCall" blocks with "arguments" (not "tool_use" with "input")
- Tool results are separate "toolResult" messages (not inline blocks)
- Tool names are lowercase (read, write, edit, bash)
- Edit uses edits array [{oldText, newText}] not flat old_string/new_string

The Pi source normalizes all of this to Claude's format so shared formatting works.
"""

import json
from pathlib import Path

from agentkb.chats.sources.pi import (
    parse_jsonl,
    _normalize_tool_arguments,
    _normalize_content_blocks,
)


# --- parse_jsonl: basic messages ---


def test_pi_user_and_assistant(tmp_path):
    """User and assistant text messages normalize correctly."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "session", "version": 3, "id": "abc"}),
        json.dumps({"type": "message", "timestamp": "2026-04-15T00:01:00Z",
                     "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}}),
        json.dumps({"type": "message", "timestamp": "2026-04-15T00:01:05Z",
                     "message": {"role": "assistant",
                                 "content": [{"type": "text", "text": "Hi there!"}]}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[0]["content"][0]["text"] == "hello"
    assert messages[1]["content"][0]["text"] == "Hi there!"


def test_pi_skips_non_message_entries(tmp_path):
    """Session header, model_change, thinking_level_change are skipped."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "session", "version": 3, "id": "abc", "timestamp": "T"}),
        json.dumps({"type": "model_change", "id": "x", "provider": "anthropic"}),
        json.dumps({"type": "thinking_level_change", "id": "y", "thinkingLevel": "medium"}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    assert len(messages) == 1


def test_pi_empty_assistant_skipped(tmp_path):
    """Pi's initial empty assistant messages (streaming stubs) are skipped."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "assistant", "content": []}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "assistant",
                                 "content": [{"type": "text", "text": "Hello!"}]}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    assert len(messages) == 2  # user + non-empty assistant only


# --- parse_jsonl: thinking blocks ---


def test_pi_thinking_blocks(tmp_path):
    """Thinking blocks pass through unchanged (same format as Claude)."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "assistant", "content": [
                         {"type": "thinking", "thinking": "Let me think..."},
                         {"type": "text", "text": "Here is my answer"},
                     ]}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    assistant = messages[1]
    assert assistant["content"][0] == {"type": "thinking", "thinking": "Let me think..."}
    assert assistant["content"][1] == {"type": "text", "text": "Here is my answer"}


# --- parse_jsonl: tool calls ---


def test_pi_tool_call_normalization(tmp_path):
    """Pi toolCall blocks normalize to tool_use with capitalized names."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "user", "content": [{"type": "text", "text": "read file"}]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "assistant", "content": [
                         {"type": "toolCall", "name": "read", "arguments": {"path": "/tmp/a.py"}}
                     ]}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    tool_block = messages[1]["content"][0]
    assert tool_block["type"] == "tool_use"
    assert tool_block["name"] == "Read"
    assert tool_block["input"]["file_path"] == "/tmp/a.py"


# --- parse_jsonl: tool results ---


def test_pi_tool_result_appended_to_assistant(tmp_path):
    """toolResult messages become tool_result blocks on the preceding assistant."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "user", "content": [{"type": "text", "text": "do it"}]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "assistant", "content": [
                         {"type": "toolCall", "name": "read", "arguments": {"path": "/tmp/a.py"}}
                     ]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "toolResult", "toolCallId": "x", "toolName": "read",
                                 "content": [{"type": "text", "text": "file contents"}],
                                 "isError": False}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    assert len(messages) == 2  # user + assistant (toolResult merged)
    assistant = messages[1]
    assert len(assistant["content"]) == 2  # tool_use + tool_result
    assert assistant["content"][1]["type"] == "tool_result"
    assert assistant["content"][1]["content"] == "file contents"
    assert assistant["content"][1]["is_error"] is False


def test_pi_error_tool_result(tmp_path):
    """Error tool results normalize with is_error=True."""
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "user", "content": [{"type": "text", "text": "do it"}]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "assistant", "content": [
                         {"type": "toolCall", "name": "bash", "arguments": {"command": "fail"}}
                     ]}}),
        json.dumps({"type": "message", "timestamp": "T",
                     "message": {"role": "toolResult", "toolCallId": "x", "toolName": "bash",
                                 "content": [{"type": "text", "text": "command not found"}],
                                 "isError": True}}),
    ]
    jsonl.write_text("\n".join(lines))
    messages = parse_jsonl(jsonl)
    result_block = messages[1]["content"][-1]
    assert result_block["is_error"] is True
    assert result_block["content"] == "command not found"


# --- _normalize_tool_arguments ---


def test_normalize_read_args():
    """read: path -> file_path."""
    result = _normalize_tool_arguments("read", {"path": "/tmp/a.py"})
    assert result == {"file_path": "/tmp/a.py"}


def test_normalize_write_args():
    """write: path -> file_path, content passes through."""
    result = _normalize_tool_arguments("write", {"path": "f.py", "content": "code"})
    assert result == {"file_path": "f.py", "content": "code"}


def test_normalize_edit_args():
    """edit: edits array -> flat old_string/new_string from first edit."""
    result = _normalize_tool_arguments("edit", {
        "path": "test.py",
        "edits": [{"oldText": "old", "newText": "new"}, {"oldText": "a", "newText": "b"}],
    })
    assert result["file_path"] == "test.py"
    assert result["old_string"] == "old"
    assert result["new_string"] == "new"


def test_normalize_bash_args():
    """bash: command passes through unchanged."""
    result = _normalize_tool_arguments("bash", {"command": "ls -la"})
    assert result == {"command": "ls -la"}


def test_normalize_unknown_tool_args():
    """Unknown tools pass arguments through as-is."""
    result = _normalize_tool_arguments("custom_tool", {"foo": "bar"})
    assert result == {"foo": "bar"}


# --- _normalize_content_blocks ---


def test_normalize_blocks_text_and_thinking():
    """Text and thinking blocks pass through."""
    blocks = [
        {"type": "text", "text": "hello"},
        {"type": "thinking", "thinking": "hmm"},
    ]
    result = _normalize_content_blocks(blocks)
    assert result == [
        {"type": "text", "text": "hello"},
        {"type": "thinking", "thinking": "hmm"},
    ]


def test_normalize_blocks_tool_call():
    """toolCall blocks become tool_use blocks."""
    blocks = [
        {"type": "toolCall", "name": "bash", "arguments": {"command": "ls"}},
    ]
    result = _normalize_content_blocks(blocks)
    assert result[0]["type"] == "tool_use"
    assert result[0]["name"] == "Bash"
    assert result[0]["input"] == {"command": "ls"}
