"""Wiki parsing: markdown chunking and index building."""

from __future__ import annotations

import json
from pathlib import Path

from agentkb.encoder import DEFAULT_MODEL
from agentkb.indexing import (
    FileEntry,
    IndexSpec,
    MODEL_KEY,
    build_index,
)


# (subdir name, collection tag) — the wiki store fans files into two collections.
WIKI_ROOTS: list[tuple[str, str]] = [
    ("wiki", "wiki"),
    ("sources", "wiki:source"),
]


_INDEXED_SUFFIXES = (".md", ".rst")


def _list_wiki_files(wiki_root: Path) -> dict[str, FileEntry]:
    """Walk both wiki subdirs into FileEntry-keyed dict.

    Relative paths include the subdir prefix (e.g. ``wiki/foo.md``) so state
    keys and SQLite ``file`` values are unique across the two collections.
    Picks up ``.md`` and ``.rst`` files so rST-documented repos mirrored
    under ``sources/refs/`` are indexed without a conversion pass.
    """
    out: dict[str, FileEntry] = {}
    for subdir, collection in WIKI_ROOTS:
        d = wiki_root / subdir
        if not d.exists():
            continue
        for path in sorted(d.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _INDEXED_SUFFIXES:
                continue
            rel = str(path.relative_to(wiki_root))
            out[rel] = FileEntry(path=path, collection=collection)
    return out


def _make_wiki_structured_text(chunk: dict, entry: FileEntry) -> str:
    """Structured text used for semantic embedding of a wiki chunk."""
    parts = [f"[{entry.collection}] {chunk['title']}"]
    if chunk["section"] and chunk["section"] != "(full page)":
        parts[0] += f" > {chunk['section']}"
    if chunk["tags"]:
        parts.append(f"Tags: {', '.join(chunk['tags'])}")
    parts.append("")
    parts.append(chunk["content"])
    return "\n".join(parts)


WIKI_SPEC = IndexSpec(
    label="wiki",
    list_files=_list_wiki_files,
    make_structured_text=_make_wiki_structured_text,
)


def build_wiki_index(
    wiki_root: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    rebuild: bool = False,
    json_output: bool = False,
) -> dict:
    """Build the wiki search index from wiki pages and sources."""
    return build_index(
        wiki_root, index_dir, WIKI_SPEC,
        model_name=model_name, incremental=incremental, rebuild=rebuild,
        json_output=json_output,
    )


def wiki_index_is_stale(wiki_root: Path, index_dir: Path) -> bool:
    """Check if any wiki files have changed or the model has changed since last build.

    Walks both wiki subdirs by mtime — unlike the state-based staleness check
    used by chats/communications, this also catches brand-new files, which
    matters for the wiki because users frequently drop new pages in.
    """
    state_file = index_dir / "state.json"
    if not state_file.exists():
        return True

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return True

    if state.get(MODEL_KEY) != DEFAULT_MODEL:
        return True

    index_mtime = state_file.stat().st_mtime
    for subdir, _ in WIKI_ROOTS:
        d = wiki_root / subdir
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in _INDEXED_SUFFIXES:
                continue
            if f.stat().st_mtime > index_mtime:
                return True

    return False
