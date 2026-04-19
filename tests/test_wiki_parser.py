"""Tests for agentkb.wiki.parser — wiki chunking, structured text, and index building.

wiki/parser.py bridges raw markdown files and the search index. Chunks from
utils.chunk_markdown get wrapped in "structured text" — a formatted version
that includes the collection tag, title, section, and tags as a header before
the content. ColBERT encodes the structured text, so that metadata helps the
model understand context (e.g., "[wiki] Git Tips > Rebasing" tells the model
this chunk is about Git rebasing from the wiki).
"""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import agentkb.wiki.parser as wiki_parser
from agentkb.wiki.parser import _make_wiki_structured_text


# --- _make_wiki_structured_text ---
# This is the text ColBERT encodes. Prepending metadata ("[wiki] Git Tips >
# Rebasing\nTags: tools") before the content captures what the text is about
# alongside what it says, which improves retrieval — a query for "git tips"
# matches the header even when the body doesn't use those exact words.


def test_structured_text_basic():
    """Produces '[collection] Title > Section' header followed by content."""
    result = _make_wiki_structured_text("wiki", "Git Tips", "Rebasing", ["tools"], "How to rebase")
    assert "[wiki] Git Tips > Rebasing" in result
    assert "Tags: tools" in result
    assert "How to rebase" in result


def test_structured_text_full_page():
    """Omits section label when section is '(full page)'."""
    result = _make_wiki_structured_text("wiki", "Page", "(full page)", [], "Content")
    assert "> (full page)" not in result
    assert "[wiki] Page" in result


def test_structured_text_no_tags():
    """No Tags line when tags list is empty."""
    result = _make_wiki_structured_text("wiki", "Page", "Sec", [], "Content")
    assert "Tags:" not in result


# --- build_wiki_index against a fake store ---


class _FakeEncoder:
    def encode_documents(self, texts):
        return [[0.0] for _ in texts]


class _FakeStore:
    def __init__(self, index_dir):
        self.index_dir = index_dir
        self.saved_state = None
        self.saved_docs = []

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
        self.saved_docs.extend(docs)
        return list(range(len(self.saved_docs) - len(docs), len(self.saved_docs)))

    def append_plaid_index(self, _doc_ids, _embeddings):
        pass

    def save_state(self, state):
        self.saved_state = state
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
    monkeypatch.setattr("agentkb.indexing.get_encoder", lambda model_name=None: _FakeEncoder())

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


def test_build_wiki_index_namespaces_state_keys_by_subdir(monkeypatch, tmp_path):
    """State keys include the wiki/ or sources/ prefix so same-named files don't collide."""
    wiki_root = tmp_path / "wiki-root"
    (wiki_root / "wiki").mkdir(parents=True)
    (wiki_root / "sources").mkdir()
    (wiki_root / "wiki" / "foo.md").write_text("# Wiki foo\n\nPage body")
    (wiki_root / "sources" / "foo.md").write_text("# Source foo\n\nSource body")

    monkeypatch.setattr(wiki_parser, "IndexStore", _FakeStore)
    monkeypatch.setattr("agentkb.indexing.get_encoder", lambda model_name=None: _FakeEncoder())

    fake = _FakeStore(wiki_root / ".index")
    monkeypatch.setattr(wiki_parser, "IndexStore", lambda _index_dir: fake)

    stats = wiki_parser.build_wiki_index(wiki_root, wiki_root / ".index")

    assert stats["chunks_indexed"] == 2
    # Both files should be tracked with distinct, subdir-prefixed state keys.
    assert "wiki/foo.md" in fake.saved_state
    assert "sources/foo.md" in fake.saved_state
    # Document file paths are also namespaced so delete_documents_by_file is correct.
    doc_files = {d["file"] for d in fake.saved_docs}
    assert doc_files == {"wiki/foo.md", "sources/foo.md"}
