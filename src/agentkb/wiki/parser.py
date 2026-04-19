"""Wiki parsing: markdown chunking and index building."""

from __future__ import annotations

import json
from pathlib import Path

from agentkb.encoder import DEFAULT_MODEL
from agentkb.indexing import (
    MODEL_KEY,
    build_new_state,
    compute_index_diff,
    encode_and_append,
    load_old_state,
    resolve_model_change,
)
from agentkb.output import echo_status
from agentkb.store import IndexStore
from agentkb.utils import chunk_markdown


# (subdir name, collection tag) — the wiki store fans files into two collections.
WIKI_ROOTS: list[tuple[str, str]] = [
    ("wiki", "wiki"),
    ("sources", "wiki:source"),
]


def _list_wiki_files(wiki_root: Path) -> dict[str, tuple[Path, str]]:
    """Walk both wiki subdirs, returning {rel_path: (abs_path, collection)}.

    Relative paths include the subdir prefix (e.g. ``wiki/foo.md``) so state
    keys and SQLite ``file`` values are unique across the two collections.
    """
    out: dict[str, tuple[Path, str]] = {}
    for subdir, collection in WIKI_ROOTS:
        d = wiki_root / subdir
        if not d.exists():
            continue
        for md_file in sorted(d.rglob("*.md")):
            rel = str(md_file.relative_to(wiki_root))
            out[rel] = (md_file, collection)
    return out


def _make_wiki_structured_text(collection: str, title: str, section: str, tags: list, content: str) -> str:
    """Structured text used for semantic embedding of a wiki chunk."""
    parts = [f"[{collection}] {title}"]
    if section and section != "(full page)":
        parts[0] += f" > {section}"
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    parts.append("")
    parts.append(content)
    return "\n".join(parts)


def build_wiki_index(
    wiki_root: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    json_output: bool = False,
) -> dict:
    """Build the wiki search index from wiki pages and sources.

    Incremental: only re-encodes changed/new files. Removed files have their
    old documents deleted before new ones are added.
    """
    effective_model = model_name or DEFAULT_MODEL
    store = IndexStore(index_dir)

    old_state = load_old_state(store, incremental=incremental)
    old_state, _ = resolve_model_change(
        store, old_state, effective_model, label="wiki", json_output=json_output,
    )

    all_files = _list_wiki_files(wiki_root)

    new_state = build_new_state(effective_model, {rel: abs_path for rel, (abs_path, _) in all_files.items()})

    if not all_files and not old_state:
        echo_status("[agentkb] No wiki content to index.", json_output=json_output)
        if store.exists():
            store.close()
        return {"chunks_indexed": 0}

    diff = compute_index_diff(old_state, new_state, tracked_only=False)
    if old_state and diff.up_to_date:
        store.close()
        return {"chunks_indexed": 0, "up_to_date": True}

    if old_state:
        echo_status(
            f"  Wiki: {len(diff.added)} new, "
            f"{len(diff.changed)} changed, {len(diff.removed)} removed",
            json_output=json_output,
        )

    if not store.exists():
        store.create()

    stale_files = (diff.files_to_process & set(old_state.keys())) | diff.removed
    if stale_files:
        store.delete_documents_by_file(stale_files)

    # Chunk only files that changed, using wiki_root as the relative base so
    # chunk.file matches the state key exactly.
    all_chunks: list[tuple[dict, str]] = []  # (chunk, collection)
    for rel in diff.files_to_process:
        abs_path, collection = all_files[rel]
        for ch in chunk_markdown(abs_path, relative_to=wiki_root):
            all_chunks.append((ch, collection))

    if not all_chunks:
        store.save_state(new_state)
        store.close()
        return {"chunks_indexed": 0, "removed": len(diff.removed)}

    docs = []
    texts = []
    for raw, collection in all_chunks:
        structured = _make_wiki_structured_text(
            collection, raw["title"], raw["section"], raw["tags"], raw["content"]
        )
        texts.append(structured)
        docs.append({
            "collection": collection,
            "file": raw["file"],
            "line": raw["line"],
            "name": raw["title"],
            "unit_type": "chunk",
            "content": structured,
            "raw_content": raw["content"],
            "title": raw["title"],
            "section": raw["section"],
            "tags": raw.get("tags", []),
        })

    encode_and_append(store, docs, texts, model_name=model_name, label="wiki", json_output=json_output)
    store.save_state(new_state)
    store.close()

    return {
        "wiki_chunks": sum(1 for _, c in all_chunks if c == "wiki"),
        "source_chunks": sum(1 for _, c in all_chunks if c == "wiki:source"),
        "chunks_indexed": len(all_chunks),
    }


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
        for f in d.rglob("*.md"):
            if f.stat().st_mtime > index_mtime:
                return True

    return False
