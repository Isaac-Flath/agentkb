"""Shared helpers for the per-store index builders.

Each store's ``build_*_index`` has the same shape: load state, check for a
model change, diff file hashes, clear stale rows, chunk-and-encode what
changed, save state. The helpers here extract the parts that don't vary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agentkb.encoder import DEFAULT_MODEL, get_encoder
from agentkb.output import echo_status
from agentkb.store import IndexStore


MODEL_KEY = "__model__"


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
    if not old_state:
        added = {f for f in new_state if f != MODEL_KEY}
        return IndexDiff(added=added, files_to_process=added)

    changed = {
        f for f, h in new_state.items()
        if f != MODEL_KEY and f in old_state and old_state[f] != h
    }
    added = {f for f in new_state if f != MODEL_KEY and f not in old_state}
    removed = {f for f in old_state if f != MODEL_KEY and f not in new_state}

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
