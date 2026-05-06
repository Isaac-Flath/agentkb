"""Chat source registry — normalize different coding agent JSONL formats into a shared schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class ChatSource:
    """A chat history source (e.g. Claude Code, Pi)."""

    name: str
    source_dir: Callable[[], Path | None]
    parse_jsonl: Callable[[Path], list[dict]]
    project_name: Callable[[Path, str], str] | None = None


SOURCES: dict[str, ChatSource] = {}


def register(source: ChatSource):
    """Register a chat source."""
    SOURCES[source.name] = source


def get_all_sources() -> list[ChatSource]:
    """Return all registered sources."""
    return list(SOURCES.values())


def get_source(name: str) -> ChatSource:
    """Get a source by name."""
    return SOURCES[name]


# Load built-in sources for callers that import the registry directly.
import agentkb.chats.sources.claude  # noqa: E402,F401
import agentkb.chats.sources.codex  # noqa: E402,F401
import agentkb.chats.sources.pi  # noqa: E402,F401
