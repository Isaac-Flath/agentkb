"""Shared utilities: file hashing, markdown parsing, markdown chunking, and time filters."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import yaml


def file_hash(path: Path) -> str:
    """Compute a fast content hash for a file (SHA-256, 16 char prefix)."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from --- delimited block. Returns {} if none."""
    if not content.startswith("---"):
        return {}
    rest = content[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}
    try:
        return yaml.safe_load(rest[:end]) or {}
    except yaml.YAMLError:
        return {}


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text."""
    if not text.startswith("---"):
        return text
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return text
    return rest[end + 4:].lstrip("\n")


def extract_wikilinks(content: str) -> list[str]:
    """Extract [[wikilinks]] from markdown content."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def parse_page(path: Path, content: str) -> dict:
    """Parse a markdown page, extracting optional YAML frontmatter and wikilinks."""
    fm = parse_frontmatter(content)
    wikilinks = extract_wikilinks(content)

    title = fm.get("title", "") or path.stem
    page_type = fm.get("type", "")
    tags = fm.get("tags", []) or []
    sources = fm.get("sources", []) or []

    if isinstance(tags, str):
        tags = [tags]
    if isinstance(sources, str):
        sources = [sources]

    return {
        "file": path,
        "title": title,
        "type": page_type,
        "tags": tags,
        "sources": sources,
        "wikilinks": wikilinks,
    }


def chunk_markdown(
    path: Path,
    relative_to: Path | None = None,
) -> list[dict]:
    """Split a markdown file into chunks at heading boundaries.

    Returns list of dicts with: file, title, section, line, content, tags.
    This is the generic splitter — store-specific parsers add structured_text.
    """
    text = path.read_text(errors="replace")
    file_path = str(path.relative_to(relative_to)) if relative_to else str(path)

    page_info = parse_page(path, text)
    title = page_info["title"]
    tags = page_info["tags"]

    content = strip_frontmatter(text)
    lines = content.split("\n")

    # Find heading positions
    headings = []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))

    # No headings — one chunk for the whole page
    if not headings:
        if not content.strip():
            return []
        return [{
            "file": file_path,
            "title": title,
            "section": "(full page)",
            "line": 1,
            "content": content.strip(),
            "tags": tags,
        }]

    chunks = []
    for idx, (line_num, level, heading_text) in enumerate(headings):
        end_line = len(lines)
        for future_idx in range(idx + 1, len(headings)):
            if headings[future_idx][1] <= level:
                end_line = headings[future_idx][0]
                break

        chunk_content = "\n".join(lines[line_num:end_line]).strip()
        if not chunk_content:
            continue

        chunks.append({
            "file": file_path,
            "title": title,
            "section": heading_text,
            "line": line_num + 1,
            "content": chunk_content,
            "tags": tags,
        })

    return chunks


def parse_time_filter(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    """Parse ISO dates/times and simple relative phrases like "7 days".

    Supported forms:
    - YYYY-MM-DD
    - ISO datetime strings, with optional trailing Z
    - today / yesterday
    - N minutes / hours / days / weeks
    """
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    lowered = raw.lower()
    now = datetime.now(timezone.utc)

    if lowered == "today":
        base_date = now.date()
        chosen_time = time.max if end_of_day else time.min
        return datetime.combine(base_date, chosen_time, tzinfo=timezone.utc)

    if lowered == "yesterday":
        base_date = now.date() - timedelta(days=1)
        chosen_time = time.max if end_of_day else time.min
        return datetime.combine(base_date, chosen_time, tzinfo=timezone.utc)

    relative_match = re.fullmatch(
        r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks)",
        lowered,
    )
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        if unit.startswith("minute"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("hour"):
            delta = timedelta(hours=amount)
        elif unit.startswith("week"):
            delta = timedelta(weeks=amount)
        else:
            delta = timedelta(days=amount)
        return now - delta

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported time filter: {value!r}. Use ISO dates/times or phrases like '7 days'."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)

    if len(raw) == 10 and "T" not in raw and " " not in raw:
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)

    return parsed


def chunk_markdown_directory(root: Path) -> list[dict]:
    """Chunk all markdown files in a directory."""
    import sys

    chunks = []
    if not root.exists():
        return chunks

    for md_file in sorted(root.rglob("*.md")):
        try:
            chunks.extend(chunk_markdown(md_file, relative_to=root))
        except Exception as e:
            print(f"[agentkb] Warning: failed to chunk {md_file}: {e}", file=sys.stderr)

    return chunks
