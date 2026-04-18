"""Tests for agentkb.utils — file hashing, frontmatter, markdown chunking.

utils.py is the foundation layer that everything else builds on. It handles
the lowest-level operations: hashing files to detect changes, parsing markdown
frontmatter for metadata, and splitting markdown into chunks at heading
boundaries. Both the wiki and chat indexing pipelines depend on these functions.
"""

from pathlib import Path

from agentkb.utils import (
    file_hash,
    parse_frontmatter,
    strip_frontmatter,
    extract_wikilinks,
    parse_page,
    chunk_markdown,
    chunk_markdown_directory,
)


# --- file_hash ---
# file_hash is the basis for incremental indexing. Every time you run
# `agentkb index`, it compares the current hash of each file against the
# hash stored from the last run. Only files whose hash changed get
# re-encoded by ColBERT. Without this, every index rebuild would re-encode
# all documents (expensive — ColBERT encoding is the slowest step).


def test_file_hash_deterministic(tmp_path):
    """file_hash returns the same 16-char hex prefix for the same content."""
    f = tmp_path / "a.txt"
    f.write_text("hello world")
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2
    assert len(h1) == 16


def test_file_hash_changes_with_content(tmp_path):
    """Different content produces different hashes."""
    f = tmp_path / "a.txt"
    f.write_text("version 1")
    h1 = file_hash(f)
    f.write_text("version 2")
    h2 = file_hash(f)
    assert h1 != h2


# --- parse_frontmatter / strip_frontmatter ---
# Wiki pages and chat exports use YAML frontmatter (the --- block at the top)
# to store metadata like title, tags, date, session_id. parse_frontmatter
# extracts this into a dict; strip_frontmatter removes it so the body text
# can be chunked and embedded without the YAML noise.


def test_parse_frontmatter_basic():
    """Extracts YAML between --- delimiters."""
    content = "---\ntitle: My Page\ntags:\n  - python\n  - search\n---\n\nBody text."
    fm = parse_frontmatter(content)
    assert fm["title"] == "My Page"
    assert fm["tags"] == ["python", "search"]


def test_parse_frontmatter_missing():
    """Returns empty dict when no frontmatter."""
    assert parse_frontmatter("Just some text") == {}


def test_parse_frontmatter_malformed():
    """Returns empty dict when YAML is broken."""
    assert parse_frontmatter("---\n: bad: yaml: [unclosed\n---\n") == {}


def test_strip_frontmatter_removes_yaml():
    """Strips the --- block and returns the body."""
    content = "---\ntitle: X\n---\n\nBody here."
    assert strip_frontmatter(content) == "Body here."


def test_strip_frontmatter_no_frontmatter():
    """Passes through text unchanged when no frontmatter."""
    assert strip_frontmatter("No frontmatter") == "No frontmatter"


# --- extract_wikilinks ---
# Wiki pages can reference each other with [[wikilinks]]. These are extracted
# to build cross-references between pages (e.g., a Go concurrency page linking
# to a CRDT page where the lesson was originally learned).


def test_extract_wikilinks():
    """Finds [[wikilink]] patterns in content."""
    text = "See [[Go Concurrency]] and also [[DaVinci Resolve API]]."
    links = extract_wikilinks(text)
    assert links == ["Go Concurrency", "DaVinci Resolve API"]


def test_extract_wikilinks_none():
    """Returns empty list when no wikilinks."""
    assert extract_wikilinks("No links here") == []


# --- parse_page ---
# parse_page combines frontmatter extraction and wikilink extraction into
# a single metadata dict for a markdown file. This is used during indexing
# to attach title, tags, and link info to each chunk.


def test_parse_page_with_frontmatter(tmp_path):
    """parse_page extracts title, tags, wikilinks from a markdown file."""
    p = tmp_path / "my-page.md"
    p.write_text("---\ntitle: My Page\ntags: [python]\n---\n\nSee [[Other Page]].")
    result = parse_page(p, p.read_text())
    assert result["title"] == "My Page"
    assert result["tags"] == ["python"]
    assert result["wikilinks"] == ["Other Page"]


def test_parse_page_no_frontmatter(tmp_path):
    """Falls back to filename stem when no title in frontmatter."""
    p = tmp_path / "fallback-title.md"
    p.write_text("Just body text.")
    result = parse_page(p, p.read_text())
    assert result["title"] == "fallback-title"
    assert result["tags"] == []


# --- chunk_markdown ---
# chunk_markdown is the core splitting logic used by both wiki and chat indexing.
# It breaks a markdown file into chunks at heading boundaries. Each chunk becomes
# a separate document in the search index with its own embedding. This is important
# because ColBERT works best on focused, topic-sized text — a whole 500-line wiki
# page would dilute the embedding, but a single "## Rebasing" section gives a
# strong, specific signal.


def test_chunk_markdown_single_heading(tmp_path):
    """A page with one heading produces one chunk."""
    p = tmp_path / "page.md"
    p.write_text("# Main Heading\n\nSome content here.\nMore content.")
    chunks = chunk_markdown(p)
    assert len(chunks) == 1
    assert chunks[0]["section"] == "Main Heading"
    assert "Some content here." in chunks[0]["content"]


def test_chunk_markdown_multiple_headings(tmp_path):
    """Splits at heading boundaries — each heading starts a new chunk."""
    p = tmp_path / "multi.md"
    p.write_text("# First\n\nAAA\n\n# Second\n\nBBB\n\n# Third\n\nCCC")
    chunks = chunk_markdown(p)
    assert len(chunks) == 3
    assert chunks[0]["section"] == "First"
    assert chunks[1]["section"] == "Second"
    assert chunks[2]["section"] == "Third"


def test_chunk_markdown_nested_headings(tmp_path):
    """A ## under a # is included in the #'s chunk (until next same-or-higher level)."""
    p = tmp_path / "nested.md"
    p.write_text("# Top\n\nIntro\n\n## Sub\n\nDetails\n\n# Another\n\nMore")
    chunks = chunk_markdown(p)
    # "Top" chunk includes ## Sub since Sub is lower level
    assert len(chunks) == 3
    assert chunks[0]["section"] == "Top"
    assert chunks[1]["section"] == "Sub"
    assert chunks[2]["section"] == "Another"


def test_chunk_markdown_no_headings(tmp_path):
    """A page with no headings becomes one chunk labeled '(full page)'."""
    p = tmp_path / "flat.md"
    p.write_text("Just a paragraph.\n\nAnother paragraph.")
    chunks = chunk_markdown(p)
    assert len(chunks) == 1
    assert chunks[0]["section"] == "(full page)"


def test_chunk_markdown_empty_file(tmp_path):
    """An empty file produces no chunks."""
    p = tmp_path / "empty.md"
    p.write_text("")
    chunks = chunk_markdown(p)
    assert chunks == []


def test_chunk_markdown_relative_to(tmp_path):
    """relative_to makes file paths relative to a root directory.

    This matters because the stored file path is what gets shown in search
    results — "tools/git.md" is useful, "/var/tmp/abc123/wiki/tools/git.md" is not.
    """
    sub = tmp_path / "wiki" / "tools"
    sub.mkdir(parents=True)
    p = sub / "git.md"
    p.write_text("# Git\n\nContent")
    chunks = chunk_markdown(p, relative_to=tmp_path / "wiki")
    assert chunks[0]["file"] == "tools/git.md"


def test_chunk_markdown_with_frontmatter(tmp_path):
    """Frontmatter is stripped from content but title/tags are extracted.

    The frontmatter YAML shouldn't end up in the chunk content (it would
    pollute the embedding), but its metadata should be preserved.
    """
    p = tmp_path / "page.md"
    p.write_text("---\ntitle: Custom Title\ntags: [api]\n---\n\n# Section\n\nBody")
    chunks = chunk_markdown(p)
    assert chunks[0]["title"] == "Custom Title"
    assert chunks[0]["tags"] == ["api"]
    assert "---" not in chunks[0]["content"]


# --- chunk_markdown_directory ---
# Convenience wrapper that recursively finds all .md files in a directory
# and chunks them all. Used by both wiki and chat indexing to process
# their respective directories in one call.


def test_chunk_markdown_directory(tmp_path):
    """Recursively chunks all .md files in a directory."""
    (tmp_path / "a.md").write_text("# Page A\n\nContent A")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("# Page B\n\nContent B")

    chunks = chunk_markdown_directory(tmp_path)
    files = {c["file"] for c in chunks}
    assert "a.md" in files
    assert "sub/b.md" in files


def test_chunk_markdown_directory_nonexistent(tmp_path):
    """Returns empty list for a directory that doesn't exist."""
    assert chunk_markdown_directory(tmp_path / "nope") == []
