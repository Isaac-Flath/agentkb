"""Tests for agentkb.config — Settings persistence and path resolution.

config.py has two jobs:
1. Settings — a JSON config file (~/.agentkb/config.json) that stores user
   preferences like which git remotes to sync with, custom paths, and defaults.
   The CLI reads these to know where wiki/chats/skills live and how to behave.
2. paths — a central resolver for all directory locations (wiki, chats, skills,
   etc). Other modules never hardcode paths; they call paths.wiki_dir() etc.
   This lets users override locations via settings or in-project overrides.
"""

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from agentkb import cli
from agentkb.config import Settings, SETTINGS_DEFAULTS, paths, find_in_project_wiki


# --- Settings ---
# Settings persists to ~/.agentkb/config.json. It holds things like git remote
# URLs for sync, S3 bucket for traceability backup, and default search parameters.
# The CLI's `agentkb settings set` command writes here, and everything else reads.


def test_settings_defaults(tmp_path):
    """Fresh Settings object has all default values."""
    config_file = tmp_path / "config.json"
    with patch.object(paths, "config_file", return_value=config_file):
        s = Settings()
    assert s.get("default_scope") == "wiki"
    assert s.get("top_k") == 3


def test_settings_set_and_persist(tmp_path):
    """set() writes to disk; a new Settings instance reads it back."""
    config_file = tmp_path / "config.json"
    with patch.object(paths, "config_file", return_value=config_file):
        s = Settings()
        s.set("default_scope", "chats")
        assert s.get("default_scope") == "chats"

        # Read back from disk
        s2 = Settings()
        assert s2.get("default_scope") == "chats"


def test_settings_int_coercion(tmp_path):
    """Integer settings are coerced from string input (like CLI args).

    Click passes CLI arguments as strings, so `agentkb settings set top_k 25`
    arrives as the string "25". Settings coerces it to int based on the default's type.
    """
    config_file = tmp_path / "config.json"
    with patch.object(paths, "config_file", return_value=config_file):
        s = Settings()
        s.set("top_k", "25")
        assert s.get("top_k") == 25
        assert isinstance(s.get("top_k"), int)


def test_settings_all(tmp_path):
    """all() returns the full settings dict."""
    config_file = tmp_path / "config.json"
    with patch.object(paths, "config_file", return_value=config_file):
        s = Settings()
        all_settings = s.all()
    assert set(SETTINGS_DEFAULTS.keys()).issubset(set(all_settings.keys()))


def test_cli_settings_json_outputs_resolved_paths(tmp_path):
    """`agentkb settings --json` returns machine-readable settings and resolved paths."""
    runner = CliRunner()
    config_file = tmp_path / "config.json"
    wiki_root = tmp_path / "wiki-root"
    chats_root = tmp_path / "chats-root"
    communications_root = tmp_path / "communications-root"
    references_root = tmp_path / "references-root"
    skills_root = tmp_path / "skills-root"

    with patch.object(paths, "config_file", return_value=config_file), \
         patch.object(paths, "agentkb_home", return_value=tmp_path), \
         patch.object(paths, "wiki_dir", return_value=wiki_root), \
         patch.object(paths, "chats_dir", return_value=chats_root), \
         patch.object(paths, "chats_sessions_dir", return_value=chats_root / "sessions"), \
         patch.object(paths, "chats_readable_dir", return_value=chats_root / "readable"), \
         patch.object(paths, "communications_dir", return_value=communications_root), \
         patch.object(paths, "references_dir", return_value=references_root), \
         patch.object(paths, "skills_dir", return_value=skills_root):
        result = runner.invoke(cli.main, ["settings", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["config_file"] == str(config_file)
    assert payload["settings"]["default_scope"] == "wiki"
    assert payload["resolved_paths"] == {
        "agentkb_home": str(tmp_path),
        "wiki_root": str(wiki_root),
        "wiki_pages": str(wiki_root / "wiki"),
        "wiki_sources": str(wiki_root / "sources"),
        "chats_root": str(chats_root),
        "chats_sessions": str(chats_root / "sessions"),
        "chats_readable": str(chats_root / "readable"),
        "communications_root": str(communications_root),
        "references_root": str(references_root),
        "skills_root": str(skills_root),
    }


# --- find_in_project_wiki ---
# agentkb supports per-project wiki overrides. If a project has a .agentkb/wiki
# or .knowledge directory, that's used instead of the global ~/.agentkb/wiki.
# This lets a project carry its own knowledge base that travels with the repo.


def test_find_in_project_wiki_agentkb(tmp_path):
    """Finds .agentkb/wiki directory if it exists."""
    wiki_dir = tmp_path / ".agentkb" / "wiki"
    wiki_dir.mkdir(parents=True)
    assert find_in_project_wiki(tmp_path) == wiki_dir


def test_find_in_project_wiki_knowledge(tmp_path):
    """Falls back to .knowledge directory."""
    know_dir = tmp_path / ".knowledge"
    know_dir.mkdir()
    assert find_in_project_wiki(tmp_path) == know_dir


def test_find_in_project_wiki_none(tmp_path):
    """Returns None when neither override exists."""
    assert find_in_project_wiki(tmp_path) is None
