"""Chat index building over the readable markdown produced by renderer.py."""

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


def _make_chat_structured_text(chunk: dict, entry: FileEntry) -> str:
    """Structured text used for semantic embedding of a chat chunk."""
    parts = [f"[chats] {chunk['title']}"]
    if chunk["section"] and chunk["section"] != "(full page)":
        parts[0] += f" > {chunk['section']}"
    if chunk["tags"]:
        parts.append(f"Tags: {', '.join(chunk['tags'])}")
    parts.append("")
    parts.append(chunk["content"])
    return "\n".join(parts)


CHAT_SPEC = IndexSpec(
    label="chat",
    list_files=partial(list_markdown_files, collection="chats"),
    make_structured_text=_make_chat_structured_text,
)


def build_chat_index(
    projects_dir: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    rebuild: bool = False,
    tracked_only: bool = False,
    json_output: bool = False,
) -> dict:
    """Build the chat history search index from readable markdown files."""
    return build_index(
        projects_dir, index_dir, CHAT_SPEC,
        model_name=model_name, incremental=incremental, rebuild=rebuild,
        tracked_only=tracked_only, json_output=json_output,
    )


def chat_index_is_stale(readable_dir: Path, index_dir: Path) -> bool:
    """Check if any tracked readable markdown file has changed since last index build."""
    return index_is_stale_from_state(readable_dir, index_dir)
