"""Communications source registry — normalize different communication platforms into a shared readable format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class CommunicationSource:
    """A communications source (e.g. X/Twitter, Slack).

    Unlike chat sources (which copy local JSONL), communications sources
    actively fetch from an API or export into a raw directory owned by
    agentkb, then render readable markdown from that raw layer.
    """

    name: str
    # Fetch new data from the source into raw_dir. Returns stats dict.
    fetch: Callable[[Path], dict]
    # Render readable markdown from raw_dir into readable_dir. Returns stats dict.
    render: Callable[[Path, Path], dict]


SOURCES: dict[str, CommunicationSource] = {}


def register(source: CommunicationSource):
    """Register a communication source."""
    SOURCES[source.name] = source
