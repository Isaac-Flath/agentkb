"""Wiki parsing: markdown chunking and index building."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentkb.utils import file_hash, chunk_markdown_directory
from agentkb.encoder import get_encoder
from agentkb.output import echo_status
from agentkb.store import IndexStore


@dataclass
class WikiChunk:
    """A chunk of a wiki markdown document."""
    file: str
    collection: str  # "wiki" or "wiki:source"
    title: str
    section: str
    line: int
    content: str
    tags: list[str]
    structured_text: str = ""


def _make_structured_text(collection: str, title: str, section: str, tags: list[str], content: str) -> str:
    """Generate structured text for embedding a wiki chunk."""
    parts = [f"[{collection}] {title}"]
    if section and section != "(full page)":
        parts[0] += f" > {section}"
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    parts.append("")
    parts.append(content)
    return "\n".join(parts)


def chunk_wiki_directory(root: Path, collection: str = "wiki") -> list[WikiChunk]:
    """Chunk all markdown files in a wiki directory into WikiChunks with structured text."""
    raw_chunks = chunk_markdown_directory(root)
    chunks = []
    for raw in raw_chunks:
        structured = _make_structured_text(
            collection, raw["title"], raw["section"], raw["tags"], raw["content"]
        )
        chunks.append(WikiChunk(
            file=raw["file"],
            collection=collection,
            title=raw["title"],
            section=raw["section"],
            line=raw["line"],
            content=raw["content"],
            tags=raw["tags"],
            structured_text=structured,
        ))
    return chunks


def build_wiki_index(
    wiki_root: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    json_output: bool = False,
) -> dict:
    """Build the wiki search index from wiki pages and sources.

    Truly incremental: only re-encodes changed/new files and appends to the
    existing PLAID index. Deleted/changed files have their old documents removed
    before new ones are added.
    """
    from agentkb.encoder import DEFAULT_MODEL
    effective_model = model_name or DEFAULT_MODEL

    store = IndexStore(index_dir)

    old_state = {}
    if incremental and store.exists():
        old_state = store.load_state()

    # Model change forces full rebuild
    if old_state and old_state.get("__model__") != effective_model:
        echo_status(f"[agentkb] Model changed to {effective_model}, rebuilding index...", json_output=json_output)
        old_state = {}
        if store.exists():
            store.clear()

    wiki_chunks = chunk_wiki_directory(wiki_root / "wiki", collection="wiki")
    source_chunks = chunk_wiki_directory(wiki_root / "sources", collection="wiki:source")
    all_chunks = wiki_chunks + source_chunks

    if not all_chunks and not old_state:
        echo_status("[agentkb] No wiki content to index.", json_output=json_output)
        if store.exists():
            store.close()
        return {"chunks_indexed": 0}

    # Build file hash state for all current files.
    # Chunk file paths are relative to their subdirectory (wiki/ or sources/),
    # so resolve against wiki_root by checking both possible subdirs.
    new_state = {"__model__": effective_model}
    for chunk in all_chunks:
        if chunk.file in new_state:
            continue
        # Try resolving through the collection subdirectory
        subdir = "sources" if chunk.collection == "wiki:source" else "wiki"
        fpath = wiki_root / subdir / chunk.file
        if fpath.exists():
            new_state[chunk.file] = file_hash(fpath)

    # Determine which files changed
    if incremental and old_state:
        changed_files = {f for f, h in new_state.items()
                         if not f.startswith("__") and old_state.get(f) != h}
        new_files = {f for f in new_state
                     if not f.startswith("__") and f not in old_state}
        removed_files = {f for f in old_state
                         if not f.startswith("__") and f not in new_state}
        files_to_process = changed_files | new_files

        if not files_to_process and not removed_files:
            store.close()
            return {"chunks_indexed": 0, "up_to_date": True}

        echo_status(
            f"  Wiki: {len(new_files)} new, "
            f"{len(changed_files)} changed, {len(removed_files)} removed",
            json_output=json_output,
        )
    else:
        files_to_process = {f for f in new_state if not f.startswith("__")}
        removed_files = set()

    if not store.exists():
        store.create()

    # Remove stale documents (changed or deleted files)
    stale_files = (files_to_process & set(old_state.keys())) | removed_files
    if stale_files:
        store.delete_documents_by_file(stale_files)

    # Only encode chunks from changed/new files
    chunks_to_index = [c for c in all_chunks if c.file in files_to_process]

    if not chunks_to_index:
        # Only removals, no new content
        store.save_state(new_state)
        store.close()
        return {"chunks_indexed": 0, "removed": len(removed_files)}

    encoder = get_encoder(model_name=model_name)
    texts = [chunk.structured_text for chunk in chunks_to_index]

    echo_status(f"[agentkb] Encoding {len(texts)} wiki chunks with ColBERT...", json_output=json_output)
    embeddings = encoder.encode_documents(texts)

    docs = []
    for chunk in chunks_to_index:
        docs.append({
            "collection": chunk.collection,
            "file": chunk.file,
            "line": chunk.line,
            "name": chunk.title,
            "unit_type": "chunk",
            "content": chunk.structured_text,
            "raw_content": chunk.content,
            "title": chunk.title,
            "section": chunk.section,
            "tags": chunk.tags,
        })

    doc_ids = store.add_documents(docs)

    echo_status("[agentkb] Updating PLAID index...", json_output=json_output)
    store.append_plaid_index(doc_ids, embeddings)
    store.save_state(new_state)
    store.close()

    return {
        "wiki_chunks": sum(1 for c in chunks_to_index if c.collection == "wiki"),
        "source_chunks": sum(1 for c in chunks_to_index if c.collection == "wiki:source"),
        "chunks_indexed": len(chunks_to_index),
    }


def wiki_index_is_stale(wiki_root: Path, index_dir: Path) -> bool:
    """Check if any wiki files have changed or model has changed since last index build."""
    state_file = index_dir / "state.json"
    if not state_file.exists():
        return True

    # Check model mismatch
    import json
    from agentkb.encoder import DEFAULT_MODEL
    try:
        state = json.loads(state_file.read_text())
        if state.get("__model__") != DEFAULT_MODEL:
            return True
    except (json.JSONDecodeError, OSError):
        return True

    index_mtime = state_file.stat().st_mtime

    for subdir in ("wiki", "sources"):
        d = wiki_root / subdir
        if not d.exists():
            continue
        for f in d.rglob("*.md"):
            if f.stat().st_mtime > index_mtime:
                return True

    return False
