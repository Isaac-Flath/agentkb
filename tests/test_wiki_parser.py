"""Tests for agentkb.wiki.parser — wiki chunking and structured text.

wiki/parser.py bridges the gap between raw markdown files and the search index.
It takes the generic chunks from utils.chunk_markdown and wraps them in
WikiChunk objects with "structured text" — a formatted version that includes
the collection tag, title, section, and tags as a header before the content.
This structured text is what gets embedded by ColBERT, so it carries metadata
that helps the model understand context (e.g., "[wiki] Git Tips > Rebasing"
tells the model this chunk is about Git rebasing from the wiki).
"""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import agentkb.wiki.parser as wiki_parser
from agentkb.wiki.parser import WikiChunk, _make_structured_text, chunk_wiki_directory


# --- _make_structured_text ---
# This is the text that ColBERT actually encodes. By prepending metadata
# ("[wiki] Git Tips > Rebasing\nTags: tools") before the content, the embedding
# captures not just what the text says but what it's about and where it lives.
# This improves retrieval — a query for "git tips" matches the header even if
# the body text doesn't use those exact words.


def test_structured_text_basic():
    """Produces '[collection] Title > Section' header followed by content."""
    result = _make_structured_text("wiki", "Git Tips", "Rebasing", ["tools"], "How to rebase")
    assert "[wiki] Git Tips > Rebasing" in result
    assert "Tags: tools" in result
    assert "How to rebase" in result


def test_structured_text_full_page():
    """Omits section label when section is '(full page)'."""
    result = _make_structured_text("wiki", "Page", "(full page)", [], "Content")
    assert "> (full page)" not in result
    assert "[wiki] Page" in result


def test_structured_text_no_tags():
    """No Tags line when tags list is empty."""
    result = _make_structured_text("wiki", "Page", "Sec", [], "Content")
    assert "Tags:" not in result


# --- chunk_wiki_directory ---
# This is the main entry point for wiki indexing. It takes a directory of
# markdown files, chunks them at heading boundaries, and produces WikiChunk
# objects ready to be encoded and stored. The collection parameter distinguishes
# wiki pages ("wiki") from ingested source documents ("wiki:source").


def test_chunk_wiki_directory(tmp_path):
    """Chunks all .md files and produces WikiChunk objects with structured text."""
    (tmp_path / "page.md").write_text("---\ntitle: My Page\ntags: [demo]\n---\n\n# Section\n\nBody text")

    chunks = chunk_wiki_directory(tmp_path, collection="wiki")
    assert len(chunks) == 1
    assert isinstance(chunks[0], WikiChunk)
    assert chunks[0].collection == "wiki"
    assert chunks[0].title == "My Page"
    assert chunks[0].section == "Section"
    assert "[wiki] My Page > Section" in chunks[0].structured_text
    assert "Body text" in chunks[0].structured_text


def test_chunk_wiki_directory_empty(tmp_path):
    """Returns empty list for directory with no markdown."""
    (tmp_path / "readme.txt").write_text("not markdown")
    assert chunk_wiki_directory(tmp_path) == []


class _FakeEncoder:
    def encode_documents(self, texts):
        return [[0.0] for _ in texts]


class _FakeStore:
    def __init__(self, index_dir):
        self.index_dir = index_dir

    def exists(self):
        return False

    def load_state(self):
        return {}

    def clear(self):
        pass

    def create(self):
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def delete_documents_by_file(self, _files):
        pass

    def add_documents(self, docs):
        return list(range(len(docs)))

    def append_plaid_index(self, _doc_ids, _embeddings):
        pass

    def save_state(self, _state):
        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.index_dir / "state.json").write_text("{}")

    def close(self):
        pass


def test_build_wiki_index_json_output_writes_progress_to_stderr(monkeypatch, tmp_path):
    """json_output routes wiki indexing progress to stderr, not stdout."""
    wiki_root = tmp_path / "wiki-root"
    (wiki_root / "wiki").mkdir(parents=True)
    (wiki_root / "sources").mkdir()
    (wiki_root / "wiki" / "page.md").write_text("---\ntitle: My Page\n---\n\n# Section\n\nBody text")

    monkeypatch.setattr(wiki_parser, "IndexStore", _FakeStore)
    monkeypatch.setattr(wiki_parser, "get_encoder", lambda model_name=None: _FakeEncoder())

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        stats = wiki_parser.build_wiki_index(
            wiki_root,
            wiki_root / ".index",
            json_output=True,
        )

    assert stats["chunks_indexed"] == 1
    assert stdout.getvalue() == ""
    assert "Encoding 1 wiki chunks with ColBERT" in stderr.getvalue()
    assert "Updating PLAID index" in stderr.getvalue()
