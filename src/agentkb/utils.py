"""Shared utilities: file hashing, markdown parsing, and markdown chunking."""

from __future__ import annotations

import hashlib
import re
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


def parse_page(path: Path, content: str) -> dict:
    """Parse a markdown page, returning title and tags from optional YAML frontmatter."""
    fm = parse_frontmatter(content)

    title = fm.get("title", "") or path.stem
    tags = fm.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]

    return {"title": title, "tags": tags}


RST_UNDERLINE_CHARS = set("=-~^\"'`*+#<>:")


def _find_markdown_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return list of ``(line_index, level, heading_text)`` for ATX headings."""
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))
    return headings


def _find_rst_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return list of ``(line_index, level, heading_text)`` for rST headings.

    Scans for a text line immediately followed by an underline of a single
    repeated char (``=``/``-``/``~`` etc., see ``RST_UNDERLINE_CHARS``) at
    least as long as the heading. Overlined headings still get picked up —
    the overline doesn't match (its "text" is all punctuation and its
    following line is the title text, not an underline), but the next
    iteration catches the title + bottom underline pair.

    Levels follow Sphinx's "first-seen" convention: the first distinct
    underline char encountered becomes level 1, the next distinct char
    becomes level 2, etc.
    """
    first_seen: dict[str, int] = {}
    headings: list[tuple[int, int, str]] = []

    i = 0
    while i < len(lines) - 1:
        text_line = lines[i]
        under = lines[i + 1]
        stripped_under = under.strip()
        stripped_text = text_line.strip()

        if (
            stripped_text
            and stripped_under
            and len(stripped_under) >= len(stripped_text)
            and len(set(stripped_under)) == 1
            and stripped_under[0] in RST_UNDERLINE_CHARS
        ):
            char = stripped_under[0]
            if char not in first_seen:
                first_seen[char] = len(first_seen) + 1
            headings.append((i, first_seen[char], stripped_text))
            i += 2
            continue
        i += 1
    return headings


def chunk_markdown(
    path: Path,
    relative_to: Path | None = None,
) -> list[dict]:
    """Split a markdown or reStructuredText file into chunks at heading boundaries.

    Returns list of dicts with: file, title, section, line, content, tags.
    Dispatches on extension: ``.rst`` uses underline-style heading detection;
    everything else uses ATX ``#`` markdown headings.
    """
    text = path.read_text(errors="replace")
    file_path = str(path.relative_to(relative_to)) if relative_to else str(path)

    page_info = parse_page(path, text)
    title = page_info["title"]
    tags = page_info["tags"]

    content = strip_frontmatter(text)
    lines = content.split("\n")

    is_rst = path.suffix.lower() == ".rst"
    headings = _find_rst_headings(lines) if is_rst else _find_markdown_headings(lines)

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


