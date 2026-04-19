"""Fetchers: populate a destination directory from an external source.

Each fetcher takes (ref, dest) and writes files into ``dest``. Network/IO
errors propagate — the caller decides whether to abort the sync or skip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import requests

from agentkb.config import paths
from agentkb.references.convert import html_to_markdown
from agentkb.references.manifest import Ref


def fetch(ref: Ref, dest: Path) -> str | None:
    """Dispatch to the right fetcher. Returns optional provenance token.

    For ``git``, the return value is the HEAD commit sha after pull. Callers
    store it on the ref so `refs list` can show the pinned revision.
    """
    match ref.kind:
        case "git":
            return _fetch_git(ref, dest)
        case "url":
            _fetch_url(ref, dest)
            return None
        case _:
            raise ValueError(f"Unknown fetcher kind: {ref.kind!r}")


# --- git -------------------------------------------------------------


def _git_cache_dir() -> Path:
    """Cache of bare-ish clones, kept outside the wiki tree to avoid nested git."""
    return paths.agentkb_home() / "references" / "_cache"


def _fetch_git(ref: Ref, dest: Path) -> str:
    """Clone or pull into a cache, then mirror ``subpath`` (or everything) into dest.

    The cache keeps ``.git``; dest does not. This avoids nesting git repos
    inside the wiki while still allowing cheap incremental pulls.
    """
    cache = _git_cache_dir() / ref.id
    cache.parent.mkdir(parents=True, exist_ok=True)

    if (cache / ".git").exists():
        subprocess.run(
            ["git", "-C", str(cache), "fetch", "--depth=1", "origin"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(cache), "reset", "--hard", "origin/HEAD"],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["git", "clone", "--depth=1", ref.source, str(cache)],
            check=True, capture_output=True,
        )

    commit = subprocess.run(
        ["git", "-C", str(cache), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    src_root = cache / ref.subpath if ref.subpath else cache
    if not src_root.exists():
        raise FileNotFoundError(
            f"subpath {ref.subpath!r} not found in {ref.source} (expected {src_root})"
        )

    _mirror_tree(src_root, dest)
    return commit


def _mirror_tree(src: Path, dest: Path) -> None:
    """Copy ``src`` to ``dest``, skipping .git and preserving only what's
    useful for indexing."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for path in src.rglob("*"):
        rel = path.relative_to(src)
        # Skip .git and other dot-dirs
        if any(part.startswith(".") for part in rel.parts):
            continue
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


# --- url -------------------------------------------------------------


def _fetch_url(ref: Ref, dest: Path) -> None:
    """Fetch a single URL. Save raw HTML + converted markdown side by side."""
    resp = requests.get(ref.source, timeout=30, headers={
        "User-Agent": "agentkb/0.3 (+https://github.com/anthropics/agentkb)",
    })
    resp.raise_for_status()

    dest.mkdir(parents=True, exist_ok=True)
    html = resp.text
    (dest / "source.html").write_text(html)
    (dest / "source.md").write_text(html_to_markdown(html))
    (dest / "_source_url.txt").write_text(ref.source + "\n")
