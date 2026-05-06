"""Tests for Codex CLI rollout parsing."""

import json

from agentkb.chats.sources.codex import parse_jsonl, project_name


def test_codex_parses_user_assistant_and_tools(tmp_path):
    """Codex event streams normalize to the shared chat schema."""
    jsonl = tmp_path / "rollout-2026-05-06T12-00-00-abc123.jsonl"
    lines = [
        json.dumps({
            "timestamp": "2026-05-06T12:00:00Z",
            "type": "session_meta",
            "payload": {"cwd": "/tmp/my-project"},
        }),
        json.dumps({
            "timestamp": "2026-05-06T12:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "environment context"}],
            },
        }),
        json.dumps({
            "timestamp": "2026-05-06T12:00:02Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "Fix the bug"},
        }),
        json.dumps({
            "timestamp": "2026-05-06T12:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I will inspect it."}],
            },
        }),
        json.dumps({
            "timestamp": "2026-05-06T12:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "rg bug", "workdir": "/tmp/my-project"}),
                "call_id": "call_1",
            },
        }),
        json.dumps({
            "timestamp": "2026-05-06T12:00:05Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "match",
            },
        }),
        json.dumps({
            "timestamp": "2026-05-06T12:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "input": "*** Begin Patch\n*** End Patch\n",
                "call_id": "call_2",
            },
        }),
    ]
    jsonl.write_text("\n".join(lines))

    messages = parse_jsonl(jsonl)

    assert len(messages) == 2
    assert messages[0] == {
        "role": "user",
        "content": "Fix the bug",
        "timestamp": "2026-05-06T12:00:02Z",
    }
    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "I will inspect it."}
    assert assistant["content"][1]["type"] == "tool_use"
    assert assistant["content"][1]["name"] == "exec_command"
    assert assistant["content"][1]["input"]["cmd"] == "rg bug"
    assert assistant["content"][2]["type"] == "tool_result"
    assert assistant["content"][2]["content"] == "match"
    assert assistant["content"][3]["name"] == "apply_patch"


def test_codex_project_name_uses_session_cwd(tmp_path):
    """Codex project labels come from session_meta cwd."""
    jsonl = tmp_path / "rollout.jsonl"
    jsonl.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"cwd": "/Users/me/git/agentkb"},
    }))

    assert project_name(jsonl, "2026/05/06/rollout.jsonl") == "agentkb"


def test_codex_falls_back_to_response_item_user_without_user_event(tmp_path):
    """Older Codex logs without event_msg/user_message still render."""
    jsonl = tmp_path / "old-rollout.jsonl"
    jsonl.write_text("\n".join([
        json.dumps({
            "timestamp": "2026-01-02T12:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "older prompt"}],
            },
        }),
        json.dumps({
            "timestamp": "2026-01-02T12:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "older answer"}],
            },
        }),
    ]))

    messages = parse_jsonl(jsonl)

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == [{"type": "text", "text": "older prompt"}]
    assert messages[1]["role"] == "assistant"
