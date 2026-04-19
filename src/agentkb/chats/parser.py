"""Chat index building over the readable markdown produced by renderer.py."""

from __future__ import annotations

from pathlib import Path

from agentkb.encoder import DEFAULT_MODEL
from agentkb.indexing import (
    build_new_state,
    compute_index_diff,
    encode_and_append,
    index_is_stale_from_state,
    load_old_state,
    resolve_model_change,
    save_merged_state,
)
from agentkb.output import echo_status
from agentkb.store import IndexStore
from agentkb.utils import chunk_markdown


def _list_all_md(root: Path, project_filter: str | None = None) -> dict[str, Path]:
    """List readable markdown files, keyed by path relative to root."""
    files = {}
    if not root.exists():
        return files
    for md_file in sorted(root.rglob("*.md")):
        if md_file.name.startswith("_"):
            continue
        rel = str(md_file.relative_to(root))
        if project_filter and project_filter not in rel:
            continue
        files[rel] = md_file
    return files


def _make_chat_structured_text(title: str, section: str, tags: list, content: str) -> str:
    """Structured text used for semantic embedding of a chat chunk."""
    parts = [f"[chats] {title}"]
    if section and section != "(full page)":
        parts[0] += f" > {section}"
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    parts.append("")
    parts.append(content)
    return "\n".join(parts)


def build_chat_index(
    projects_dir: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    project_filter: str | None = None,
    tracked_only: bool = False,
    json_output: bool = False,
) -> dict:
    """Build the chat history search index from readable markdown files.

    Args:
        projects_dir: Path to the readable/ directory (not JSONL).
        tracked_only: If True, only update files already in the index.
    """
    effective_model = model_name or DEFAULT_MODEL
    store = IndexStore(index_dir)

    old_state = load_old_state(store, incremental=incremental)
    old_state, forced_full = resolve_model_change(
        store, old_state, effective_model, label="chat", json_output=json_output,
    )
    if forced_full:
        tracked_only = False

    if tracked_only and old_state:
        all_files = {
            rel: projects_dir / rel
            for rel in old_state
            if rel != "__model__" and (projects_dir / rel).exists()
        }
    else:
        all_files = _list_all_md(projects_dir, project_filter=project_filter)

    new_state = build_new_state(effective_model, all_files)

    if not all_files and not old_state:
        echo_status("[agentkb] No chat history found.", json_output=json_output)
        return {"sessions_parsed": 0, "chunks_indexed": 0}

    diff = compute_index_diff(old_state, new_state, tracked_only=tracked_only)
    if old_state and diff.up_to_date:
        store.close()
        return {"sessions_parsed": 0, "chunks_indexed": 0, "up_to_date": True}

    if old_state:
        echo_status(
            f"[agentkb] Chat index: {len(diff.added)} new, "
            f"{len(diff.changed)} changed, {len(diff.removed)} removed",
            json_output=json_output,
        )

    if not store.exists():
        store.create()

    stale_files = (diff.files_to_process & set(old_state.keys())) | diff.removed
    if stale_files:
        store.delete_documents_by_file(stale_files)

    all_chunks = []
    for rel_path in diff.files_to_process:
        all_chunks.extend(chunk_markdown(all_files[rel_path], relative_to=projects_dir))

    echo_status(
        f"  Parsed {len(diff.files_to_process)} sessions, found {len(all_chunks)} new chunks",
        json_output=json_output,
    )

    docs = []
    texts = []
    for raw in all_chunks:
        structured = _make_chat_structured_text(
            raw["title"], raw["section"], raw["tags"], raw["content"]
        )
        texts.append(structured)
        docs.append({
            "collection": "chats",
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

    encode_and_append(store, docs, texts, model_name=model_name, label="chat", json_output=json_output)
    save_merged_state(store, old_state, new_state, tracked_only=tracked_only)
    store.close()

    return {
        "sessions_parsed": len(diff.files_to_process),
        "chunks_indexed": len(all_chunks),
    }


def chat_index_is_stale(readable_dir: Path, index_dir: Path) -> bool:
    """Check if any tracked readable markdown file has changed since last index build."""
    return index_is_stale_from_state(readable_dir, index_dir)
