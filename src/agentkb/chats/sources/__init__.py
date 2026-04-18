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
