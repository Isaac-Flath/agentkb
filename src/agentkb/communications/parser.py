"""Communications indexing — builds the search index from readable markdown."""

from __future__ import annotations

import json
from pathlib import Path

from agentkb.encoder import DEFAULT_MODEL, get_encoder
from agentkb.output import echo_status
from agentkb.store import IndexStore
from agentkb.utils import chunk_markdown, file_hash


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

    old_state = {}
    if incremental and store.exists():
        old_state = store.load_state()

    if old_state and old_state.get("__model__") != effective_model:
        echo_status(
            f"[agentkb] Model changed to {effective_model}, rebuilding communications index...",
            json_output=json_output,
        )
        old_state = {}
        tracked_only = False
        if store.exists():
            store.clear()

    if tracked_only and old_state:
        all_files = {}
        for rel_path in old_state:
            if rel_path.startswith("__"):
                continue
            abs_path = readable_dir / rel_path
            if abs_path.exists():
                all_files[rel_path] = abs_path
    else:
        all_files = _list_all_md(readable_dir)

    new_state = {"__model__": effective_model}
    for rel_path, abs_path in all_files.items():
        new_state[rel_path] = file_hash(abs_path)

    if not all_files and not old_state:
        echo_status("[agentkb] No communications found.", json_output=json_output)
        return {"files_parsed": 0, "chunks_indexed": 0}

    if old_state:
        changed = {f for f, h in new_state.items()
                   if not f.startswith("__") and old_state.get(f) != h}
        new_files = {f for f in new_state
                     if not f.startswith("__") and f not in old_state}
        removed = {f for f in old_state
                   if not f.startswith("__") and f not in new_state}
        if tracked_only:
            new_files = set()
            removed = set()
        to_process = changed | new_files

        if not to_process and not removed:
            store.close()
            return {"files_parsed": 0, "chunks_indexed": 0, "up_to_date": True}

        echo_status(
            f"[agentkb] Communications index: {len(new_files)} new, "
            f"{len(changed)} changed, {len(removed)} removed",
            json_output=json_output,
        )
    else:
        to_process = set(all_files.keys())
        removed = set()

    if not store.exists():
        store.create()

    stale = (to_process & set(old_state.keys())) | removed
    if stale:
        store.delete_documents_by_file(stale)

    all_chunks = []
    per_chunk_meta = []
    for rel_path in to_process:
        abs_path = all_files[rel_path]
        fm_meta = _extract_frontmatter_meta(abs_path)
        chunks = chunk_markdown(abs_path, relative_to=readable_dir)
        for ch in chunks:
            all_chunks.append(ch)
            per_chunk_meta.append(fm_meta)

    echo_status(
        f"  Parsed {len(to_process)} files, found {len(all_chunks)} new chunks",
        json_output=json_output,
    )

    if all_chunks:
        encoder = get_encoder(model_name=model_name)

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

        echo_status(
            f"[agentkb] Encoding {len(texts)} communication chunks with ColBERT...",
            json_output=json_output,
        )
        embeddings = encoder.encode_documents(texts)

        doc_ids = store.add_documents(docs)

        echo_status("[agentkb] Updating PLAID index...", json_output=json_output)
        store.append_plaid_index(doc_ids, embeddings)

    if tracked_only and old_state:
        merged_state = dict(old_state)
        merged_state.update(new_state)
        store.save_state(merged_state)
    else:
        store.save_state(new_state)
    store.close()

    return {
        "files_parsed": len(to_process),
        "chunks_indexed": len(all_chunks),
    }


def communications_index_is_stale(readable_dir: Path, index_dir: Path) -> bool:
    """Check whether any tracked readable file has changed since last index build."""
    state_file = index_dir / "state.json"
    if not state_file.exists():
        return False

    index_mtime = state_file.stat().st_mtime
    if not readable_dir.exists():
        return False

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return True

    if state.get("__model__") != DEFAULT_MODEL:
        return True

    for rel_path in state:
        if rel_path.startswith("__"):
            continue
        abs_path = readable_dir / rel_path
        if not abs_path.exists():
            return True
        if abs_path.stat().st_mtime > index_mtime:
            return True

    return False
