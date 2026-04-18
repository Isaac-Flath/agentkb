"""Sync agentkb data to/from git remotes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from agentkb.config import paths, Settings


def _check_git():
    """Check if git is installed."""
    if not shutil.which("git"):
        raise RuntimeError("git is not installed.")


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _is_git_repo(path: Path) -> bool:
    """Check if a path is inside a git repository."""
    if not path.exists():
        return False
    result = _git(["rev-parse", "--git-dir"], cwd=path, check=False)
    return result.returncode == 0


def _ensure_repo(local_path: Path, remote_url: str) -> None:
    """Clone the remote if local_path doesn't exist, or verify it's a git repo."""
    if not local_path.exists():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", remote_url, str(local_path)], cwd=local_path.parent)
    elif not _is_git_repo(local_path):
        raise RuntimeError(
            f"{local_path} exists but is not a git repository.\n"
            f"Either remove it and let agentkb clone from {remote_url},\n"
            f"or run `git init && git remote add origin {remote_url}` inside it."
        )


def _get_stores() -> list[tuple[str, Path, str]]:
    """Return (name, local_path, remote_url) for each configured store."""
    s = Settings()
    stores = []

    if s.get("wiki_remote"):
        stores.append(("wiki", paths.wiki_dir(), s.get("wiki_remote")))

    if s.get("chats_remote"):
        stores.append(("chats", paths.chats_dir(), s.get("chats_remote")))

    if s.get("communications_remote"):
        stores.append(("communications", paths.communications_dir(), s.get("communications_remote")))

    if s.get("skills_remote"):
        stores.append(("skills", paths.skills_dir(), s.get("skills_remote")))

    return stores


def push(dry_run: bool = False, verbose: bool = False) -> dict:
    """Commit and push local changes to configured git remotes."""
    _check_git()
    stores = _get_stores()
    if not stores:
        raise RuntimeError(
            "No git remotes configured. Set them with:\n"
            "  agentkb settings set wiki_remote \"git@github.com:user/wiki.git\"\n"
            "  agentkb settings set chats_remote \"git@github.com:user/chats.git\"\n"
            "  agentkb settings set communications_remote \"git@github.com:user/communications.git\"\n"
            "  agentkb settings set skills_remote \"git@github.com:user/skills.git\""
        )

    results = {}
    for name, local_path, remote_url in stores:
        if not local_path.exists():
            results[name] = "skipped (not found locally)"
            continue

        if not _is_git_repo(local_path):
            results[name] = "skipped (not a git repo)"
            continue

        try:
            # Stage all changes
            _git(["add", "-A"], cwd=local_path)

            # Check if there's anything to commit
            status = _git(["status", "--porcelain"], cwd=local_path)
            if not status.stdout.strip():
                results[name] = "up to date"
                continue

            if dry_run:
                changed = len(status.stdout.strip().splitlines())
                results[name] = f"dry-run: {changed} file(s) would be pushed"
                continue

            # Commit and push
            _git(["commit", "-m", f"agentkb sync: update {name}"], cwd=local_path)
            result = _git(["push"], cwd=local_path, check=False)
            if result.returncode != 0:
                results[name] = f"committed but push failed: {result.stderr.strip()}"
            else:
                results[name] = "ok"

        except RuntimeError as e:
            results[name] = f"error: {e}"

    return results


def pull(dry_run: bool = False, verbose: bool = False) -> dict:
    """Pull latest changes from configured git remotes."""
    _check_git()
    stores = _get_stores()
    if not stores:
        raise RuntimeError(
            "No git remotes configured. Set them with:\n"
            "  agentkb settings set wiki_remote \"git@github.com:user/wiki.git\"\n"
            "  agentkb settings set chats_remote \"git@github.com:user/chats.git\"\n"
            "  agentkb settings set communications_remote \"git@github.com:user/communications.git\"\n"
            "  agentkb settings set skills_remote \"git@github.com:user/skills.git\""
        )

    results = {}
    for name, local_path, remote_url in stores:
        try:
            if not local_path.exists():
                if dry_run:
                    results[name] = f"dry-run: would clone from {remote_url}"
                    continue
                _ensure_repo(local_path, remote_url)
                results[name] = "cloned"
                continue

            if not _is_git_repo(local_path):
                results[name] = "skipped (exists but not a git repo)"
                continue

            if dry_run:
                result = _git(["fetch", "--dry-run"], cwd=local_path, check=False)
                results[name] = "dry-run: would pull"
                continue

            _git(["pull", "--rebase"], cwd=local_path)
            results[name] = "ok"

        except RuntimeError as e:
            results[name] = f"error: {e}"

    return results


def status() -> dict:
    """Return sync status for each configured store."""
    s = Settings()
    info = {}

    for name, dir_fn in [
        ("wiki", paths.wiki_dir),
        ("chats", paths.chats_dir),
        ("communications", paths.communications_dir),
        ("skills", paths.skills_dir),
    ]:
        remote = s.get(f"{name}_remote")
        if remote:
            local = dir_fn()
            info[name] = {
                "local": str(local),
                "remote": remote,
                "exists": local.exists(),
                "is_repo": _is_git_repo(local) if local.exists() else False,
            }
        else:
            info[name] = {"remote": None}

    return info
