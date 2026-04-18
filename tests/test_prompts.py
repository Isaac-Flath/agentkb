"""Tests for agentkb.prompts — prompt resolution order.

prompts/ handles loading prompt templates used by CLI commands like
`agentkb consolidate`. Prompts can be overridden at three levels:
1. Direct file path (for custom one-off prompts)
2. User override in ~/.agentkb/prompts/ (permanent personal customization)
3. Shipped defaults in the package (fallback)

This layered resolution lets users customize the consolidation prompt
(or any future prompt) without modifying the package.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agentkb.prompts import resolve_prompt


def test_resolve_shipped_default():
    """Finds the shipped consolidate_chats prompt."""
    text = resolve_prompt("consolidate_chats")
    assert len(text) > 0
    # The shipped prompt should have placeholder variables
    assert "{since}" in text or "{paths}" in text


def test_resolve_user_override(tmp_path):
    """User override in ~/.agentkb/prompts/ takes precedence over shipped default."""
    prompts_dir = tmp_path / ".agentkb" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "consolidate_chats.md").write_text("Custom prompt: {since}")

    with patch("pathlib.Path.home", return_value=tmp_path):
        text = resolve_prompt("consolidate_chats")
    assert text == "Custom prompt: {since}"


def test_resolve_direct_file(tmp_path):
    """A file path resolves directly to that file."""
    p = tmp_path / "my_prompt.md"
    p.write_text("Direct file prompt")
    text = resolve_prompt(str(p))
    assert text == "Direct file prompt"


def test_resolve_missing():
    """Raises FileNotFoundError for nonexistent prompt."""
    with pytest.raises(FileNotFoundError):
        resolve_prompt("nonexistent_prompt_xyz")


def test_consolidate_communications_prompt_formats_cleanly():
    """The shipped consolidate_communications prompt must str.format cleanly.

    Literal braces in the prompt body (e.g. filename examples like {handle})
    need to be doubled, or .format() raises KeyError — a trap worth catching.
    """
    text = resolve_prompt("consolidate_communications")
    assert "{since}" in text and "{paths}" in text
    # If literal braces aren't escaped, this line raises KeyError.
    rendered = text.format(paths="- Wiki: /tmp/wiki", since="7 days")
    assert "7 days" in rendered
    assert "/tmp/wiki" in rendered
    # Escaped literals should appear un-escaped in the output.
    assert "{handle}" in rendered
    assert "{slug}" in rendered


def test_consolidate_chats_prompt_formats_cleanly():
    """Same guard for the chats prompt."""
    text = resolve_prompt("consolidate_chats")
    rendered = text.format(paths="- Wiki: /tmp/wiki", since="7 days")
    assert "7 days" in rendered
