"""Communications indexing — builds the search index from readable markdown."""

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


def _list_all_md(root: Path) -> dict[str, Path]:
    """List readable markdown files (excluding _index.md)."""
    files = {}
    if not root.exists():
        return files
    for md in sorted(root.rglob("*.md")):
        if md.name.startswith("_"):
            continue
        files[str(md.relative_to(root))] = md
    return files


def _make_communications_structured_text(
    title: str,
    section: str,
    tags: list,
    content: str,
    handle: str,
    source: str,
) -> str:
    """Structured text used for semantic embedding."""
    header = f"[communications:{source}]"
    if handle:
        header += f" @{handle}"
    header += f" — {title}"
    if section and section != "(full page)":
        header += f" > {section}"
    parts = [header]
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    parts.append("")
    parts.append(content)
    return "\n".join(parts)


def _extract_frontmatter_meta(md_path: Path) -> dict:
    """Cheap frontmatter read — we only need source + handle for structured text."""
    from agentkb.utils import parse_frontmatter
    try:
        text = md_path.read_text(errors="replace")
    except OSError:
        return {}
    fm = parse_frontmatter(text)
    return {
        "source": str(fm.get("source") or ""),
        "handle": str(fm.get("handle") or ""),
    }


def build_communications_index(
    readable_dir: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    tracked_only: bool = False,
    json_output: bool = False,
) -> dict:
    """Build the communications search index from readable markdown.

    Incremental: only re-encodes changed/new files.
    """
    effective_model = model_name or DEFAULT_MODEL
    store = IndexStore(index_dir)

    old_state = load_old_state(store, incremental=incremental)
    old_state, forced_full = resolve_model_change(
        store, old_state, effective_model, label="communications", json_output=json_output,
    )
    if forced_full:
        tracked_only = False

    if tracked_only and old_state:
        all_files = {
            rel: readable_dir / rel
            for rel in old_state
            if rel != "__model__" and (readable_dir / rel).exists()
        }
    else:
        all_files = _list_all_md(readable_dir)

    new_state = build_new_state(effective_model, all_files)

    if not all_files and not old_state:
        echo_status("[agentkb] No communications found.", json_output=json_output)
        return {"files_parsed": 0, "chunks_indexed": 0}

    diff = compute_index_diff(old_state, new_state, tracked_only=tracked_only)
    if old_state and diff.up_to_date:
        store.close()
        return {"files_parsed": 0, "chunks_indexed": 0, "up_to_date": True}

    if old_state:
        echo_status(
            f"[agentkb] Communications index: {len(diff.added)} new, "
            f"{len(diff.changed)} changed, {len(diff.removed)} removed",
            json_output=json_output,
        )

    if not store.exists():
        store.create()

    stale = (diff.files_to_process & set(old_state.keys())) | diff.removed
    if stale:
        store.delete_documents_by_file(stale)

    all_chunks = []
    per_chunk_meta = []
    for rel_path in diff.files_to_process:
        abs_path = all_files[rel_path]
        fm_meta = _extract_frontmatter_meta(abs_path)
        chunks = chunk_markdown(abs_path, relative_to=readable_dir)
        for ch in chunks:
            all_chunks.append(ch)
            per_chunk_meta.append(fm_meta)

    echo_status(
        f"  Parsed {len(diff.files_to_process)} files, found {len(all_chunks)} new chunks",
        json_output=json_output,
    )

    docs = []
    texts = []
    for raw, fm in zip(all_chunks, per_chunk_meta):
        structured = _make_communications_structured_text(
            raw["title"], raw["section"], raw["tags"], raw["content"],
            handle=fm.get("handle", ""),
            source=fm.get("source", "unknown"),
        )
        texts.append(structured)
        docs.append({
            "collection": "communications",
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

    encode_and_append(store, docs, texts, model_name=model_name, label="communication", json_output=json_output)
    save_merged_state(store, old_state, new_state, tracked_only=tracked_only)
    store.close()

    return {
        "files_parsed": len(diff.files_to_process),
        "chunks_indexed": len(all_chunks),
    }


def communications_index_is_stale(readable_dir: Path, index_dir: Path) -> bool:
    """Return True if any tracked readable file has changed since last index build."""
    return index_is_stale_from_state(readable_dir, index_dir)
