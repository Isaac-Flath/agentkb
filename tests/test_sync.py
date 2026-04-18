"""Tests for agentkb.sync — git push/pull against local repos.

sync.py manages syncing agentkb data (wiki, chats, skills) to/from git remotes.
Each store (wiki, chats, skills) can have its own git remote configured via
`agentkb settings set wiki_remote "git@github.com:user/wiki.git"`. This lets
you back up your knowledge base and share it across machines.

push() does: git add -A, git commit, git push for each configured store.
pull() does: git clone (if missing) or git pull --rebase for each store.

These tests use real git repos in tmp_path (bare repos as "remotes") to test
the full git workflow without any network access.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agentkb.config import Settings, paths
from agentkb.sync import push, pull, status, _is_git_repo


def _git(args, cwd):
    """Run git in a directory."""
    subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=True)


def _init_bare_repo(path):
    """Create a bare git repo (acts as the remote)."""
    path.mkdir(parents=True)
    _git(["init", "--bare"], cwd=path)


def _init_repo_with_remote(local_path, remote_path):
    """Create a git repo with a remote pointing to a bare repo."""
    local_path.mkdir(parents=True)
    _git(["init"], cwd=local_path)
    _git(["remote", "add", "origin", str(remote_path)], cwd=local_path)
    # Need an initial commit so push works
    (local_path / "README.md").write_text("init")
    _git(["add", "."], cwd=local_path)
    _git(["commit", "-m", "init"], cwd=local_path)
    _git(["push", "-u", "origin", "main"], cwd=local_path)


def _mock_settings(tmp_path, wiki_remote="", chats_remote="", communications_remote="", skills_remote=""):
    """Create a patched Settings that uses tmp_path for everything.

    sync.py reads Settings and paths to find remotes and local directories.
    These patches redirect everything to tmp_path so tests don't touch the
    real ~/.agentkb.
    """
    config_file = tmp_path / "config.json"
    wiki_dir = tmp_path / "wiki"
    chats_dir = tmp_path / "chats"
    communications_dir = tmp_path / "communications"
    skills_dir = tmp_path / "skills"

    def mock_config_file():
        return config_file

    def mock_wiki_dir():
        return wiki_dir

    def mock_chats_dir():
        return chats_dir

    def mock_communications_dir():
        return communications_dir

    def mock_skills_dir():
        return skills_dir

    patches = [
        patch.object(paths, "config_file", mock_config_file),
        patch.object(paths, "wiki_dir", mock_wiki_dir),
        patch.object(paths, "chats_dir", mock_chats_dir),
        patch.object(paths, "communications_dir", mock_communications_dir),
        patch.object(paths, "skills_dir", mock_skills_dir),
    ]

    # Write config
    import json
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({
        "wiki_remote": wiki_remote,
        "chats_remote": chats_remote,
        "communications_remote": communications_remote,
        "skills_remote": skills_remote,
    }))

    return patches


# --- _is_git_repo ---


def test_is_git_repo_true(tmp_path):
    """Returns True for an initialized git directory."""
    _git(["init"], cwd=tmp_path)
    assert _is_git_repo(tmp_path)


def test_is_git_repo_false(tmp_path):
    """Returns False for a plain directory."""
    assert not _is_git_repo(tmp_path)


def test_is_git_repo_nonexistent(tmp_path):
    """Returns False for a path that doesn't exist."""
    assert not _is_git_repo(tmp_path / "nope")


# --- push ---
# push() is called by `agentkb sync push`. It iterates over each configured
# store, stages all changes, commits with a standard message, and pushes.
# If nothing changed, it reports "up to date" without creating empty commits.


def test_push_commits_and_pushes(tmp_path):
    """push() stages, commits, and pushes changes to the remote."""
    remote = tmp_path / "remote-wiki.git"
    _init_bare_repo(remote)

    local = tmp_path / "wiki"
    _init_repo_with_remote(local, remote)

    patches = _mock_settings(tmp_path, wiki_remote=str(remote))
    for p in patches:
        p.start()
    try:
        # Create a new file
        (local / "wiki" / "test.md").parent.mkdir(parents=True, exist_ok=True)
        (local / "wiki" / "test.md").write_text("# Test Page")

        results = push()
        assert results["wiki"] == "ok"
    finally:
        for p in patches:
            p.stop()


def test_push_up_to_date(tmp_path):
    """push() reports 'up to date' when nothing changed."""
    remote = tmp_path / "remote-wiki.git"
    _init_bare_repo(remote)

    local = tmp_path / "wiki"
    _init_repo_with_remote(local, remote)

    patches = _mock_settings(tmp_path, wiki_remote=str(remote))
    for p in patches:
        p.start()
    try:
        results = push()
        assert results["wiki"] == "up to date"
    finally:
        for p in patches:
            p.stop()


def test_push_dry_run(tmp_path):
    """push(dry_run=True) reports what would happen without doing it."""
    remote = tmp_path / "remote-wiki.git"
    _init_bare_repo(remote)

    local = tmp_path / "wiki"
    _init_repo_with_remote(local, remote)
    (local / "new.md").write_text("new content")

    patches = _mock_settings(tmp_path, wiki_remote=str(remote))
    for p in patches:
        p.start()
    try:
        results = push(dry_run=True)
        assert "dry-run" in results["wiki"]
    finally:
        for p in patches:
            p.stop()


def test_push_no_remotes(tmp_path):
    """push() raises RuntimeError when no remotes are configured."""
    patches = _mock_settings(tmp_path)
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError, match="No git remotes"):
            push()
    finally:
        for p in patches:
            p.stop()


# --- pull ---
# pull() is called by `agentkb sync pull`. It clones repos that don't exist
# locally yet, or does git pull --rebase on existing ones. This is how you
# set up agentkb on a new machine — configure the remotes, run pull, and
# your wiki/chats/skills are all there.


def test_pull_clones_if_missing(tmp_path):
    """pull() clones the repo if the local directory doesn't exist."""
    remote = tmp_path / "remote-wiki.git"
    _init_bare_repo(remote)

    # Don't create local — pull should clone it
    patches = _mock_settings(tmp_path, wiki_remote=str(remote))
    for p in patches:
        p.start()
    try:
        results = pull()
        assert results["wiki"] == "cloned"
        assert (tmp_path / "wiki").exists()
    finally:
        for p in patches:
            p.stop()


def test_pull_updates_existing(tmp_path):
    """pull() does a git pull on an already-cloned repo."""
    remote = tmp_path / "remote-wiki.git"
    _init_bare_repo(remote)

    local = tmp_path / "wiki"
    _init_repo_with_remote(local, remote)

    patches = _mock_settings(tmp_path, wiki_remote=str(remote))
    for p in patches:
        p.start()
    try:
        results = pull()
        assert results["wiki"] == "ok"
    finally:
        for p in patches:
            p.stop()


# --- status ---
# status() powers `agentkb sync status`. It reports which stores are configured,
# where they point, and whether the local copy exists and is a git repo.


def test_status_configured(tmp_path):
    """status() returns remote/local info for configured stores."""
    remote = tmp_path / "remote-wiki.git"
    _init_bare_repo(remote)

    local = tmp_path / "wiki"
    _init_repo_with_remote(local, remote)

    patches = _mock_settings(tmp_path, wiki_remote=str(remote))
    for p in patches:
        p.start()
    try:
        info = status()
        assert info["wiki"]["remote"] == str(remote)
        assert info["wiki"]["exists"] is True
        assert info["wiki"]["is_repo"] is True
    finally:
        for p in patches:
            p.stop()


def test_status_unconfigured(tmp_path):
    """status() returns remote=None for unconfigured stores."""
    patches = _mock_settings(tmp_path)
    for p in patches:
        p.start()
    try:
        info = status()
        assert info["wiki"]["remote"] is None
        assert info["communications"]["remote"] is None
    finally:
        for p in patches:
            p.stop()


def test_status_communications_configured(tmp_path):
    """status() returns remote/local info for configured communications store."""
    remote = tmp_path / "remote-communications.git"
    _init_bare_repo(remote)

    local = tmp_path / "communications"
    _init_repo_with_remote(local, remote)

    patches = _mock_settings(tmp_path, communications_remote=str(remote))
    for p in patches:
        p.start()
    try:
        info = status()
        assert info["communications"]["remote"] == str(remote)
        assert info["communications"]["exists"] is True
        assert info["communications"]["is_repo"] is True
    finally:
        for p in patches:
            p.stop()
