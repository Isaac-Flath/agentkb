"""Tests for AgentKB list/show commands for chats and wiki."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from agentkb import cli


def _write_chat_markdown(path: Path, *, title: str, date: str, source: str, project: str, session_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"session_id: {session_id}",
                f"project: {project}",
                f"source: {source}",
                f"date: {date}",
                "messages: 2",
                "---",
                "",
                f"# {title}",
                "",
                "Conversation body.",
            ]
        )
    )


def test_chats_list_json_returns_metadata(monkeypatch, tmp_path):
    """`agentkb chats list --json` returns stable ids and chat metadata."""
    runner = CliRunner()
    sessions_dir = tmp_path / "chats" / "sessions"
    readable_dir = tmp_path / "chats" / "readable"

    _write_chat_markdown(
        readable_dir / "2024-06" / "older.md",
        title="Older session",
        date="2024-06-15",
        source="pi",
        project="/Users/iflath/git/harpie",
        session_id="older-1",
    )
    _write_chat_markdown(
        readable_dir / "2024-06" / "newer.md",
        title="Newer session",
        date="2024-06-16",
        source="pi",
        project="/Users/iflath/git/harpie",
        session_id="newer-1",
    )

    monkeypatch.setattr(cli.paths, "chats_sessions_dir", lambda: sessions_dir)
    monkeypatch.setattr(cli.paths, "chats_readable_dir", lambda: readable_dir)
    monkeypatch.setattr("agentkb.chats.renderer.migrate_sessions_layout", lambda _sessions_dir: False)
    monkeypatch.setattr(
        "agentkb.chats.renderer.export_all_sessions",
        lambda _sessions_dir, project_filter=None: {"copied": 0, "skipped": 0, "total": 0},
    )
    monkeypatch.setattr(
        "agentkb.chats.renderer.export_readable",
        lambda _sessions_dir, _readable_dir, project_filter=None: {"generated": 0, "skipped": 0, "total": 0},
    )

    result = runner.invoke(
        cli.main,
        ["store", "chats", "list", "--source", "pi", "--project", "harpie", "--limit", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"] == {"count": 1, "store": "chats"}
    assert payload["items"][0]["id"] == "2024-06/newer.md"
    assert payload["items"][0]["title"] == "Newer session"
    assert payload["items"][0]["source"] == "pi"
    assert payload["items"][0]["project"] == "/Users/iflath/git/harpie"


def test_chats_show_json_returns_content(monkeypatch, tmp_path):
    """`agentkb chats show --json` returns the full readable markdown session."""
    runner = CliRunner()
    sessions_dir = tmp_path / "chats" / "sessions"
    readable_dir = tmp_path / "chats" / "readable"
    chat_path = readable_dir / "2024-06" / "session.md"

    _write_chat_markdown(
        chat_path,
        title="Session title",
        date="2024-06-15",
        source="claude",
        project="agentkb",
        session_id="abc123",
    )

    monkeypatch.setattr(cli.paths, "chats_sessions_dir", lambda: sessions_dir)
    monkeypatch.setattr(cli.paths, "chats_readable_dir", lambda: readable_dir)
    monkeypatch.setattr("agentkb.chats.renderer.migrate_sessions_layout", lambda _sessions_dir: False)
    monkeypatch.setattr(
        "agentkb.chats.renderer.export_all_sessions",
        lambda _sessions_dir, project_filter=None: {"copied": 0, "skipped": 0, "total": 0},
    )
    monkeypatch.setattr(
        "agentkb.chats.renderer.export_readable",
        lambda _sessions_dir, _readable_dir, project_filter=None: {"generated": 0, "skipped": 0, "total": 0},
    )

    result = runner.invoke(cli.main, ["store", "chats", "show", "--id", "2024-06/session.md", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["item"]["id"] == "2024-06/session.md"
    assert payload["item"]["title"] == "Session title"
    assert "# Session title" in payload["item"]["content"]


def test_chats_show_rejects_path_escape(monkeypatch, tmp_path):
    """Chat ids must stay inside the readable chats directory."""
    runner = CliRunner()
    sessions_dir = tmp_path / "chats" / "sessions"
    readable_dir = tmp_path / "chats" / "readable"
    readable_dir.mkdir(parents=True)

    monkeypatch.setattr(cli.paths, "chats_sessions_dir", lambda: sessions_dir)
    monkeypatch.setattr(cli.paths, "chats_readable_dir", lambda: readable_dir)
    monkeypatch.setattr("agentkb.chats.renderer.migrate_sessions_layout", lambda _sessions_dir: False)
    monkeypatch.setattr(
        "agentkb.chats.renderer.export_all_sessions",
        lambda _sessions_dir, project_filter=None: {"copied": 0, "skipped": 0, "total": 0},
    )
    monkeypatch.setattr(
        "agentkb.chats.renderer.export_readable",
        lambda _sessions_dir, _readable_dir, project_filter=None: {"generated": 0, "skipped": 0, "total": 0},
    )

    result = runner.invoke(cli.main, ["store", "chats", "show", "--id", "../secret.md"])

    assert result.exit_code != 0
    assert "readable chats directory" in result.output


def test_wiki_list_json_filters_by_tag_and_since(monkeypatch, tmp_path):
    """`agentkb wiki list --json` supports tag and recency filters."""
    runner = CliRunner()
    wiki_root = tmp_path / "wiki-root"
    pages_dir = wiki_root / "wiki" / "tools"
    pages_dir.mkdir(parents=True)

    recent = pages_dir / "recent.md"
    recent.write_text("---\ntitle: Recent\ntags: [search, tools]\n---\n\n# Recent\n")
    old = pages_dir / "old.md"
    old.write_text("---\ntitle: Old\ntags: [tools]\n---\n\n# Old\n")

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=10)
    recent_ts = now.timestamp()
    old_ts = old_time.timestamp()

    recent.touch()
    old.touch()
    import os

    os.utime(recent, (recent_ts, recent_ts))
    os.utime(old, (old_ts, old_ts))

    monkeypatch.setattr(cli.paths, "wiki_dir", lambda: wiki_root)

    result = runner.invoke(
        cli.main,
        ["store", "wiki", "list", "--tag", "search", "--since", "7 days", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["meta"] == {"count": 1, "store": "wiki"}
    assert payload["items"][0]["path"] == "tools/recent.md"
    assert payload["items"][0]["title"] == "Recent"
    assert payload["items"][0]["tags"] == ["search", "tools"]
