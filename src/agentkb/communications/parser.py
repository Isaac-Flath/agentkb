"""Communications indexing — builds the search index from readable markdown."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from agentkb.indexing import (
    FileEntry,
    IndexSpec,
    build_index,
    index_is_stale_from_state,
    list_markdown_files,
)
from agentkb.utils import parse_frontmatter


def _extract_frontmatter_meta(md_path: Path) -> dict:
    """Cheap frontmatter read — we only need source + handle for structured text."""
    try:
        text = md_path.read_text(errors="replace")
    except OSError:
        return {}
    fm = parse_frontmatter(text)
    return {
        "source": str(fm.get("source") or ""),
        "handle": str(fm.get("handle") or ""),
    }


def _make_communications_structured_text(chunk: dict, entry: FileEntry) -> str:
    """Structured text used for semantic embedding."""
    source = entry.extra.get("source") or "unknown"
    handle = entry.extra.get("handle") or ""

    header = f"[communications:{source}]"
    if handle:
        header += f" @{handle}"
    header += f" — {chunk['title']}"
    if chunk["section"] and chunk["section"] != "(full page)":
        header += f" > {chunk['section']}"

    parts = [header]
    if chunk["tags"]:
        parts.append(f"Tags: {', '.join(chunk['tags'])}")
    parts.append("")
    parts.append(chunk["content"])
    return "\n".join(parts)


COMMUNICATIONS_SPEC = IndexSpec(
    label="communications",
    list_files=partial(list_markdown_files, collection="communications", enrich=_extract_frontmatter_meta),
    make_structured_text=_make_communications_structured_text,
)


def build_communications_index(
    readable_dir: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    rebuild: bool = False,
    tracked_only: bool = False,
    json_output: bool = False,
) -> dict:
    """Build the communications search index from readable markdown."""
    return build_index(
        readable_dir, index_dir, COMMUNICATIONS_SPEC,
        model_name=model_name, incremental=incremental, rebuild=rebuild,
        tracked_only=tracked_only, json_output=json_output,
    )


def communications_index_is_stale(readable_dir: Path, index_dir: Path) -> bool:
    """Return True if any tracked readable file has changed since last index build."""
    return index_is_stale_from_state(readable_dir, index_dir)
