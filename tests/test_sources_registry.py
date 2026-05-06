"""Tests for the chat source registry."""

from agentkb.chats.sources import SOURCES, get_all_sources, get_source


def test_claude_registered():
    """Claude source is registered."""
    assert "claude" in SOURCES


def test_pi_registered():
    """Pi source is registered."""
    assert "pi" in SOURCES


def test_codex_registered():
    """Codex source is registered."""
    assert "codex" in SOURCES


def test_get_all_sources():
    """get_all_sources returns all built-in sources."""
    sources = get_all_sources()
    names = {s.name for s in sources}
    assert "claude" in names
    assert "pi" in names
    assert "codex" in names


def test_get_source():
    """get_source retrieves by name."""
    claude = get_source("claude")
    assert claude.name == "claude"
    pi = get_source("pi")
    assert pi.name == "pi"
    codex = get_source("codex")
    assert codex.name == "codex"


def test_source_dirs_are_callable():
    """source_dir is a callable that returns Path or None."""
    for source in get_all_sources():
        result = source.source_dir()
        assert result is None or hasattr(result, "exists")


def test_parse_jsonl_is_callable():
    """parse_jsonl is a callable."""
    for source in get_all_sources():
        assert callable(source.parse_jsonl)
