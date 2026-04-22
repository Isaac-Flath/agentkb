"""Chats store: coding-agent JSONL copied in, rendered to readable markdown, indexed."""

from __future__ import annotations

from agentkb.chats.renderer import export_sessions, export_readable
from agentkb.chats.parser import build_chat_index, chat_index_is_stale
from agentkb.config import paths
from agentkb.output import echo_status
from agentkb.store import IndexStore

# Register all chat sources on import
import agentkb.chats.sources.claude  # noqa: F401
import agentkb.chats.sources.pi  # noqa: F401


NOT_READY_MESSAGE = "[agentkb] No chat history found. Run `agentkb index` first."


def _sync_sessions_and_readable():
    """Copy JSONL from each registered source and regenerate readable markdown."""
    from agentkb.chats.renderer import export_all_sessions, migrate_sessions_layout

    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()

    migrate_sessions_layout(sessions_dir)
    export_all_sessions(sessions_dir)
    if sessions_dir.exists():
        export_readable(sessions_dir, readable_dir)

    return sessions_dir, readable_dir


def ensure_search_store(*, json_output: bool = False) -> IndexStore | None:
    """Re-export sessions, regenerate readable markdown, refresh the index, return a store handle."""
    _, readable_dir = _sync_sessions_and_readable()

    if not readable_dir.exists():
        return None

    index_dir = paths.chats_dir() / ".index"
    if not index_dir.exists():
        echo_status("[agentkb] Building chat index...", json_output=json_output)
        build_chat_index(readable_dir, index_dir, json_output=json_output)
    elif chat_index_is_stale(readable_dir, index_dir):
        build_chat_index(readable_dir, index_dir, tracked_only=True, json_output=json_output)

    return IndexStore(index_dir) if index_dir.exists() else None


def reindex(*, model: str | None = None, rebuild: bool = False) -> dict:
    """Run the full chats pipeline: sync JSONL, render, index. Returns build stats (or ``{}``)."""
    _, readable_dir = _sync_sessions_and_readable()
    if not readable_dir.exists():
        return {}
    return build_chat_index(readable_dir, paths.chats_dir() / ".index", model_name=model, rebuild=rebuild)


def status_lines() -> list[str]:
    """Return the ``agentkb status`` output for this store."""
    index_dir = paths.chats_dir() / ".index"
    if not index_dir.exists():
        return ["  Chat history: not indexed (run `agentkb index`)"]

    store = IndexStore(index_dir)
    if not store.exists():
        return ["  Chat history: not indexed (run `agentkb index`)"]
    line = f"  Chat history: {store.document_count()} chunks across {store.file_count()} session files"
    store.close()
    return [line]
