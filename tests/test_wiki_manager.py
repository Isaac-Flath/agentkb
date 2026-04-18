"""Tests for agentkb.wiki.manager — KnowledgeBase init, ingest, status.

KnowledgeBase manages the wiki's lifecycle. `agentkb wiki init` creates the
directory structure (wiki/ for pages, sources/ for raw documents, plus schema.md,
index.md, and log.md). The wiki is where knowledge accumulates across sessions —
things learned from debugging, API gotchas, taste decisions, etc. The schema.md
defines conventions for what belongs and how to write it.
"""

import shutil
from pathlib import Path

import pytest

from agentkb.wiki.manager import KnowledgeBase


def test_init_creates_structure(tmp_path):
    """init() creates wiki/, sources/, schema.md, index.md, log.md.

    wiki/ holds the actual knowledge pages organized by topic (tools/, writing/, etc).
    sources/ holds raw documents that were ingested. schema.md defines the writing
    conventions. index.md is a human-curated catalog. log.md tracks operations.
    """
    wiki_path = tmp_path / "wiki"
    KnowledgeBase.init(wiki_path)

    assert (wiki_path / "wiki").is_dir()
    assert (wiki_path / "sources").is_dir()
    assert (wiki_path / "schema.md").exists()
    assert (wiki_path / "index.md").exists()
    assert (wiki_path / "log.md").exists()


def test_init_refuses_existing(tmp_path):
    """init() raises FileExistsError if schema.md already exists."""
    wiki_path = tmp_path / "wiki"
    KnowledgeBase.init(wiki_path)
    with pytest.raises(FileExistsError):
        KnowledgeBase.init(wiki_path)


# ingest() is for adding raw source documents (PDFs, notes, transcripts) into
# the wiki's sources/ directory. These get indexed alongside wiki pages so they're
# searchable, but they live separately from the curated wiki content.
def test_ingest_copies_file(tmp_path):
    """ingest() copies a file into sources/ and logs it."""
    wiki_path = tmp_path / "wiki"
    KnowledgeBase.init(wiki_path)
    kb = KnowledgeBase(wiki_path)

    # Create a source file
    src = tmp_path / "my-notes.md"
    src.write_text("# My Notes\n\nSome content.")

    dest = kb.ingest(str(src))
    assert dest.exists()
    assert dest.parent.name == "sources"
    assert dest.read_text() == "# My Notes\n\nSome content."

    # Check log was updated
    log = (wiki_path / "log.md").read_text()
    assert "my-notes.md" in log


def test_ingest_missing_file(tmp_path):
    """ingest() raises FileNotFoundError for a nonexistent source."""
    wiki_path = tmp_path / "wiki"
    KnowledgeBase.init(wiki_path)
    kb = KnowledgeBase(wiki_path)

    with pytest.raises(FileNotFoundError):
        kb.ingest("/nonexistent/file.md")


# status() powers `agentkb status` and `agentkb wiki status`. It counts wiki
# pages and source files so you can see at a glance how much knowledge is stored.
def test_status(tmp_path):
    """status() counts wiki pages and source files."""
    wiki_path = tmp_path / "wiki"
    KnowledgeBase.init(wiki_path)

    # Add some pages
    tools = wiki_path / "wiki" / "tools"
    tools.mkdir(parents=True)
    (tools / "git.md").write_text("# Git")
    (tools / "python.md").write_text("# Python")
    (wiki_path / "sources" / "notes.md").write_text("# Notes")

    kb = KnowledgeBase(wiki_path)
    stats = kb.status()
    assert stats["wiki_pages"] == 2
    assert stats["sources"] == 1
