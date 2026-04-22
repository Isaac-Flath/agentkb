"""Shared helpers for the per-store index builders.

Every ``build_*_index`` has the same shape: load state, check for a model
change, diff file hashes, clear stale rows, chunk-and-encode what changed,
save state. :func:`build_index` does the whole pipeline; per-store parsers
just pass an :class:`IndexSpec` describing which files to walk and how to
format each chunk's structured embedding text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agentkb.encoder import DEFAULT_MODEL, get_encoder
from agentkb.output import echo_status
from agentkb.store import IndexStore
from agentkb.utils import chunk_markdown


MODEL_KEY = "__model__"


@dataclass
class FileEntry:
    """One file the indexer should walk, with its collection tag and any per-file metadata."""

    path: Path
    collection: str
    extra: dict = field(default_factory=dict)


@dataclass
class IndexSpec:
    """Per-store hooks for :func:`build_index`.

    ``label`` flows into progress messages (``[agentkb] Encoding 5 {label} chunks``).
    ``list_files`` walks the store's root and keys files by a path relative to
    that root. ``make_structured_text`` assembles the string that gets embedded
    for each chunk — typically a header like ``[wiki] Title > Section`` prepended
    to the raw content.
    """

    label: str
    list_files: Callable[[Path], dict[str, FileEntry]]
    make_structured_text: Callable[[dict, FileEntry], str]


def list_markdown_files(root: Path, *, collection: str,
                        enrich: Callable[[Path], dict] | None = None) -> dict[str, FileEntry]:
    """List ``.md`` files under ``root`` (skipping leading-underscore names).

    Chats and communications both use this shape — a single fixed collection
    tag applied to every file. ``enrich`` lets communications attach
    per-file frontmatter metadata.
    """
    files: dict[str, FileEntry] = {}
    if not root.exists():
        return files
    for md in sorted(root.rglob("*.md")):
        if md.name.startswith("_"):
            continue
        rel = str(md.relative_to(root))
        extra = enrich(md) if enrich else {}
        files[rel] = FileEntry(path=md, collection=collection, extra=extra)
    return files


def load_old_state(store: IndexStore, *, incremental: bool) -> dict:
    """Read the store's saved state, or return {} if not incremental or missing."""
    if incremental and store.exists():
        return store.load_state()
    return {}


def resolve_model_change(
    store: IndexStore,
    old_state: dict,
    effective_model: str,
    *,
    label: str,
    json_output: bool = False,
) -> tuple[dict, bool]:
    """If the saved model differs from the requested one, clear the store.

    Returns ``(old_state, forced_full_rebuild)``. When a rebuild is forced,
    callers should reset ``tracked_only`` to False.
    """
    if old_state and old_state.get(MODEL_KEY) != effective_model:
        echo_status(
            f"[agentkb] Model changed to {effective_model}, rebuilding {label} index...",
            json_output=json_output,
        )
        if store.exists():
            store.clear()
        return {}, True
    return old_state, False


def build_new_state(effective_model: str, all_files: dict[str, Path]) -> dict:
    """Assemble the next state dict from the current {rel_path: abs_path} map."""
    from agentkb.utils import file_hash

    state = {MODEL_KEY: effective_model}
    for rel, abs_path in all_files.items():
        state[rel] = file_hash(abs_path)
    return state


@dataclass
class IndexDiff:
    """Summary of file-level changes between two index states."""

    changed: set[str] = field(default_factory=set)
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    files_to_process: set[str] = field(default_factory=set)
    up_to_date: bool = False


def compute_index_diff(old_state: dict, new_state: dict, *, tracked_only: bool) -> IndexDiff:
    """Diff two state dicts, ignoring the ``__model__`` key.

    ``tracked_only`` restricts the diff to files already known to the index —
    new files are ignored and removed files don't trigger cleanup.
    """
    old_files = set(old_state) - {MODEL_KEY}
    new_files = set(new_state) - {MODEL_KEY}

    if not old_files:
        return IndexDiff(added=new_files, files_to_process=new_files)

    added = new_files - old_files
    removed = old_files - new_files
    changed = {f for f in old_files & new_files if old_state[f] != new_state[f]}

    if tracked_only:
        added = set()
        removed = set()

    files_to_process = changed | added
    up_to_date = not files_to_process and not removed
    return IndexDiff(changed, added, removed, files_to_process, up_to_date)


def encode_and_append(
    store: IndexStore,
    docs: list[dict],
    texts: list[str],
    *,
    model_name: str | None,
    label: str = "",
    json_output: bool = False,
) -> None:
    """Encode chunks with ColBERT, add rows to SQLite, append to PLAID.

    ``label`` gets embedded in the progress message (e.g. ``"wiki"`` →
    ``"Encoding 5 wiki chunks with ColBERT..."``). No-op if ``docs`` is empty.
    """
    if not docs:
        return

    encoder = get_encoder(model_name=model_name)
    qualifier = f"{label} " if label else ""
    echo_status(
        f"[agentkb] Encoding {len(texts)} {qualifier}chunks with ColBERT...",
        json_output=json_output,
    )
    embeddings = encoder.encode_documents(texts)

    doc_ids = store.add_documents(docs)

    echo_status("[agentkb] Updating PLAID index...", json_output=json_output)
    store.append_plaid_index(doc_ids, embeddings)


def save_merged_state(
    store: IndexStore,
    old_state: dict,
    new_state: dict,
    *,
    tracked_only: bool,
) -> None:
    """Persist state, merging into the existing state when ``tracked_only``."""
    if tracked_only and old_state:
        merged = dict(old_state)
        merged.update(new_state)
        store.save_state(merged)
    else:
        store.save_state(new_state)


def build_index(
    root: Path,
    index_dir: Path,
    spec: IndexSpec,
    *,
    model_name: str | None = None,
    incremental: bool = True,
    rebuild: bool = False,
    tracked_only: bool = False,
    json_output: bool = False,
) -> dict:
    """Run the shared index pipeline for one store.

    Returns ``{"chunks_indexed": n}`` with optional ``up_to_date`` and
    ``removed`` keys. ``rebuild`` clears the store and re-encodes from
    scratch; ``tracked_only`` skips discovery of new files (used for the
    cheap refresh path when a search runs against an already-built index).
    """
    effective_model = model_name or DEFAULT_MODEL
    store = IndexStore(index_dir)

    if rebuild:
        if store.exists():
            echo_status(
                f"[agentkb] Clearing {spec.label} index for full rebuild...",
                json_output=json_output,
            )
            store.clear()
        incremental = False
        tracked_only = False

    old_state = load_old_state(store, incremental=incremental)
    old_state, forced_full = resolve_model_change(
        store, old_state, effective_model, label=spec.label, json_output=json_output,
    )
    if forced_full:
        tracked_only = False

    discovered = spec.list_files(root)
    if tracked_only and old_state:
        all_files = {rel: entry for rel, entry in discovered.items() if rel in old_state}
    else:
        all_files = discovered

    new_state = build_new_state(
        effective_model, {rel: entry.path for rel, entry in all_files.items()},
    )

    if not all_files and not old_state:
        echo_status(f"[agentkb] No {spec.label} content to index.", json_output=json_output)
        if store.exists():
            store.close()
        return {"chunks_indexed": 0}

    diff = compute_index_diff(old_state, new_state, tracked_only=tracked_only)
    if old_state and diff.up_to_date:
        store.close()
        return {"chunks_indexed": 0, "up_to_date": True}

    if old_state:
        echo_status(
            f"[agentkb] {spec.label.capitalize()} index: {len(diff.added)} new, "
            f"{len(diff.changed)} changed, {len(diff.removed)} removed",
            json_output=json_output,
        )

    if not store.exists():
        store.create()

    stale_files = (diff.files_to_process & set(old_state)) | diff.removed
    if stale_files:
        store.delete_documents_by_file(stale_files)

    docs: list[dict] = []
    texts: list[str] = []
    for rel in diff.files_to_process:
        entry = all_files[rel]
        for chunk in chunk_markdown(entry.path, relative_to=root):
            text = spec.make_structured_text(chunk, entry)
            texts.append(text)
            docs.append({
                "collection": entry.collection,
                "file": chunk["file"],
                "line": chunk["line"],
                "name": chunk["title"],
                "unit_type": "chunk",
                "content": text,
                "raw_content": chunk["content"],
                "title": chunk["title"],
                "section": chunk["section"],
                "tags": chunk.get("tags", []),
            })

    echo_status(
        f"  Parsed {len(diff.files_to_process)} {spec.label} files, found {len(docs)} new chunks",
        json_output=json_output,
    )

    if not docs:
        save_merged_state(store, old_state, new_state, tracked_only=tracked_only)
        store.close()
        return {"chunks_indexed": 0, "removed": len(diff.removed)}

    encode_and_append(store, docs, texts, model_name=model_name, label=spec.label, json_output=json_output)
    save_merged_state(store, old_state, new_state, tracked_only=tracked_only)
    store.close()

    return {"chunks_indexed": len(docs)}


def index_is_stale_from_state(readable_dir: Path, index_dir: Path) -> bool:
    """Return True if any tracked file under ``readable_dir`` has changed.

    Only inspects files already recorded in the saved state — does NOT scan
    for new files. Use this from the cross-cutting ``agentkb search`` path
    to trigger a cheap incremental refresh without doing a full directory walk.
    """
    state_file = index_dir / "state.json"
    if not state_file.exists():
        return False
    if not readable_dir.exists():
        return False

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return True

    if state.get(MODEL_KEY) != DEFAULT_MODEL:
        return True

    index_mtime = state_file.stat().st_mtime
    for rel_path in state:
        if rel_path == MODEL_KEY:
            continue
        abs_path = readable_dir / rel_path
        if not abs_path.exists():
            return True
        if abs_path.stat().st_mtime > index_mtime:
            return True

    return False
