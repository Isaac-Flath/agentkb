"""Tests for agentkb.search — RRF fusion, regex helpers, result formatting.

search.py is the search pipeline orchestrator. When you run `agentkb search "query"`,
it runs two parallel searches (PLAID semantic + FTS5 keyword), fuses them with
Reciprocal Rank Fusion (RRF), applies post-filters (regex, glob), and formats
the results. This file tests each of those components independently.
"""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from click.testing import CliRunner

from agentkb.output import echo_status

from agentkb import cli
from agentkb.search import (
    rrf_fuse,
    strip_regex_for_semantic,
    merge_query_with_pattern,
    _compile_pattern,
    _matches_globs,
    SearchResult,
    merge_multi_collection,
)


# --- rrf_fuse ---
# RRF (Reciprocal Rank Fusion) is how semantic and keyword search results are
# combined into a single ranking. Semantic search is good at understanding meaning
# ("how do I handle errors" matches "exception handling"), while keyword search
# catches exact terms ("encode_query" finds the literal function name). RRF
# merges both by assigning scores based on rank position, not raw score — this
# works because raw scores from PLAID and FTS5 are on completely different scales.
# The alpha parameter controls the balance (default 0.75 = semantic 3x keyword).


def test_rrf_fuse_basic():
    """RRF combines two rankings into a single fused ranking."""
    semantic = [(1, 10.0), (2, 8.0), (3, 5.0)]
    keyword = [(2, 20.0), (3, 15.0), (4, 10.0)]

    fused = rrf_fuse(semantic, keyword)
    fused_ids = [doc_id for doc_id, _ in fused]

    # Doc 2 appears in both rankings, so it should rank highest
    assert fused_ids[0] == 2
    # All docs from both rankings should appear
    assert set(fused_ids) == {1, 2, 3, 4}


def test_rrf_fuse_pure_semantic():
    """alpha=1.0 means only semantic ranking matters."""
    semantic = [(1, 10.0), (2, 5.0)]
    keyword = [(2, 20.0), (3, 15.0)]

    fused = rrf_fuse(semantic, keyword, alpha=1.0)
    fused_ids = [doc_id for doc_id, _ in fused]
    # Keyword results get zero weight, so doc 3 still appears but with 0 score
    assert fused_ids[0] == 1  # top semantic result wins


def test_rrf_fuse_pure_keyword():
    """alpha=0.0 means only keyword ranking matters."""
    semantic = [(1, 10.0), (2, 5.0)]
    keyword = [(3, 20.0), (4, 15.0)]

    fused = rrf_fuse(semantic, keyword, alpha=0.0)
    fused_ids = [doc_id for doc_id, _ in fused]
    assert fused_ids[0] == 3  # top keyword result wins


# --- strip_regex_for_semantic / merge_query_with_pattern ---
# When the user passes -e (regex filter) alongside a search query, the regex
# pattern contains useful semantic information buried under metacharacters.
# For example, `agentkb search "error handling" -e "async\s+fn"` — the regex
# tells us the user cares about "async fn". strip_regex_for_semantic extracts
# those meaningful words, and merge_query_with_pattern appends them to the
# semantic query to improve ColBERT retrieval without duplicating tokens.


def test_strip_regex_basic():
    r"""Removes regex metacharacters, keeps meaningful words."""
    assert strip_regex_for_semantic(r"async\s+fn") == "async fn"


def test_strip_regex_alternation():
    """Converts | to space (OR alternatives become separate terms)."""
    assert strip_regex_for_semantic("foo|bar") == "foo bar"


def test_strip_regex_complex():
    """Handles character classes, quantifiers, groups."""
    result = strip_regex_for_semantic(r"Result<[^>]*>")
    assert "Result" in result


def test_merge_query_with_pattern():
    """Appends unique tokens from regex pattern to the query."""
    result = merge_query_with_pattern("error handling", r"async\s+fn")
    assert "error handling" in result
    assert "async" in result
    assert "fn" in result


def test_merge_query_with_pattern_deduplicates():
    """Tokens already in the query are not repeated."""
    result = merge_query_with_pattern("async error", r"async\s+fn")
    # "async" is in both, should only appear once
    assert result.count("async") == 1


def test_merge_empty_pattern():
    """Empty pattern returns the original query unchanged."""
    assert merge_query_with_pattern("hello", "") == "hello"


# --- _compile_pattern ---
# The -e, -F, and -w flags give users grep-like content filtering on top of
# search results. After RRF fusion selects the top documents, each result's
# content is checked against this compiled pattern. Results that don't match
# are discarded. This is a post-filter — it doesn't affect which documents
# the search finds, just which ones survive to be shown.


def test_compile_pattern_regex():
    """Compiles a regex pattern for content filtering."""
    pat = _compile_pattern(r"def\s+\w+")
    assert pat is not None
    assert pat.search("def my_func():")
    assert not pat.search("class MyClass:")


def test_compile_pattern_fixed():
    """fixed=True escapes regex metacharacters for literal matching."""
    pat = _compile_pattern("foo.bar", fixed=True)
    assert pat.search("foo.bar")
    assert not pat.search("fooXbar")  # . is literal, not wildcard


def test_compile_pattern_word():
    r"""word=True adds \b word boundaries."""
    pat = _compile_pattern("test", word=True)
    assert pat.search("run test now")
    assert not pat.search("testing")  # "test" is inside "testing"


def test_compile_pattern_none():
    """Returns None when no pattern is given."""
    assert _compile_pattern(None) is None
    assert _compile_pattern("") is None


# --- _matches_globs ---
# The --include and --exclude flags let users filter results by file path pattern.
# For example, `--include "*.py"` only shows Python files, `--exclude-dir tests`
# hides test directories. This is applied as a post-filter after RRF fusion.


def test_matches_globs():
    """Checks if a filepath matches any glob pattern."""
    assert _matches_globs("tools/git.md", ["*.md"])
    assert _matches_globs("tools/git.md", ["tools/*"])
    assert not _matches_globs("tools/git.md", ["*.py"])


def test_matches_globs_empty():
    """Empty pattern list matches nothing."""
    assert not _matches_globs("anything.md", [])


# --- SearchResult ---
# SearchResult is the output dataclass. format_terminal produces the human-readable
# output you see in the terminal (with [collection] tag, file:line, score, and a
# content snippet). to_json produces the machine-readable output used by agents
# (via --json flag). The terminal format includes context_lines of the content
# to give a preview without overwhelming.


def test_search_result_format_terminal():
    """format_terminal renders a human-readable snippet."""
    r = SearchResult(
        collection="wiki",
        file="tools/git.md",
        line=5,
        score=0.85,
        title="Git",
        section="Rebasing",
        raw_content="Line 1\nLine 2\nLine 3",
    )
    output = r.format_terminal(context_lines=2)
    assert "[wiki]" in output
    assert "tools/git.md:5" in output
    assert "0.85" in output
    assert "Git > Rebasing" in output
    assert "Line 1" in output
    assert "1 more lines" in output


def test_search_result_to_json():
    """to_json produces a serializable dict with key fields."""
    r = SearchResult(
        collection="chats",
        file="2024-01/session.md",
        line=1,
        score=0.7123456,
        name="my session",
        raw_content="the content",
    )
    j = r.to_json()
    assert j["collection"] == "chats"
    assert j["score"] == 0.7123  # rounded to 4 decimals
    assert j["content"] == "the content"
    assert j["name"] == "my session"


# --- merge_multi_collection ---
# When searching with --scope all, the search pipeline runs against both the
# wiki and chats indexes separately, producing two ranked lists. These can't
# be compared by raw score (different indexes, different document characteristics),
# so merge_multi_collection uses RRF to combine them by rank position. It also
# deduplicates results that appear in both (same file+line).


def test_merge_multi_collection():
    """Merges results from multiple stores using RRF, deduplicating by file+line."""
    wiki_results = [
        SearchResult(collection="wiki", file="a.md", line=1, score=0.9, content="A"),
        SearchResult(collection="wiki", file="b.md", line=1, score=0.7, content="B"),
    ]
    chat_results = [
        SearchResult(collection="chats", file="c.md", line=1, score=0.8, content="C"),
        SearchResult(collection="chats", file="a.md", line=1, score=0.6, content="A from chats"),
    ]

    merged = merge_multi_collection([wiki_results, chat_results], top_k=10)
    keys = [(r.file, r.line) for r in merged]
    # a.md:1 appears in both lists, should be ranked high and deduplicated
    assert keys.count(("a.md", 1)) == 1
    assert len(merged) == 3  # a.md, b.md, c.md (deduplicated)


class _FakeEncoder:
    def encode_query(self, _query):
        return "fake-embedding"


class _FakeTrace:
    def __init__(self, **_kwargs):
        pass

    def save(self):
        pass


def test_cli_search_json_no_indexes_stays_valid_json(monkeypatch):
    """--json must keep stdout machine-readable even when no indexes exist."""
    runner = CliRunner()

    monkeypatch.setattr(cli, "_ensure_wiki_store", lambda scope, *, json_output=False: None)
    monkeypatch.setattr(cli, "_ensure_chats_store", lambda scope, *, json_output=False: None)

    result = runner.invoke(cli.main, ["search", "query", "--json"])

    assert result.exit_code == 0
    assert '"results": []' in result.output
    assert '"message": "[agentkb] No indexes found.' in result.output


def test_cli_search_json_sends_status_to_stderr_not_stdout(monkeypatch):
    """Status chatter should go to stderr so stdout remains pure JSON."""

    def fake_ensure_wiki_store(scope, *, json_output=False):
        cli._search_status("[agentkb] Updating Wiki index...", json_output=json_output)
        return ("wiki", object())

    monkeypatch.setattr(cli, "_ensure_wiki_store", fake_ensure_wiki_store)
    monkeypatch.setattr(cli, "_ensure_chats_store", lambda scope, *, json_output=False: None)

    monkeypatch.setattr("agentkb.encoder.get_encoder", lambda: _FakeEncoder())
    monkeypatch.setattr("agentkb.encoder.DEFAULT_MODEL", "fake-model")
    monkeypatch.setattr("agentkb.search.merge_query_with_pattern", lambda query, pattern: query)
    monkeypatch.setattr("agentkb.search.search", lambda **kwargs: [
        SearchResult(collection="wiki", file="tools/test.md", line=1, score=0.9, content="A")
    ])
    monkeypatch.setattr("agentkb.search.merge_multi_collection", lambda results, top_k: results[0])
    monkeypatch.setattr("agentkb.traceability.SearchTrace", _FakeTrace)

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        cli.search.callback(
            query="query",
            scope="wiki",
            pattern=None,
            fixed=False,
            word=False,
            files_only=False,
            full_content=False,
            top_k=15,
            context_lines=6,
            json_output=True,
            include=(),
            exclude=(),
            exclude_dir=(),
            semantic_only=False,
        )

    assert '"results": [' in stdout.getvalue()
    assert "[agentkb] Updating Wiki index..." not in stdout.getvalue()
    assert "[agentkb] Updating Wiki index..." in stderr.getvalue()


def test_cli_search_json_chat_reindex_stays_valid_json(monkeypatch, tmp_path):
    """A chat reindex during search must keep stdout as valid JSON."""
    chats_root = tmp_path / "chats"
    sessions_dir = chats_root / "sessions"
    readable_dir = chats_root / "readable"
    sessions_dir.mkdir(parents=True)
    readable_dir.mkdir(parents=True)

    monkeypatch.setattr(cli.paths, "chats_dir", lambda: chats_root)
    monkeypatch.setattr(cli.paths, "chats_sessions_dir", lambda: sessions_dir)
    monkeypatch.setattr(cli.paths, "chats_readable_dir", lambda: readable_dir)
    monkeypatch.setattr("agentkb.store.IndexStore", lambda _path: object())
    monkeypatch.setattr("agentkb.chats.parser.migrate_sessions_layout", lambda _sessions_dir: False)
    monkeypatch.setattr("agentkb.chats.parser.export_all_sessions", lambda _sessions_dir: {"copied": 0, "skipped": 0, "total": 0})
    monkeypatch.setattr("agentkb.chats.parser.export_readable", lambda _sessions_dir, _readable_dir: {"generated": 0})

    seen = {}

    def fake_build_chat_index(projects_dir, index_dir, model_name=None, incremental=True,
                              project_filter=None, tracked_only=False, json_output=False):
        seen["json_output"] = json_output
        echo_status("[agentkb] Chat index: fake rebuild", json_output=json_output)
        index_dir.mkdir(parents=True, exist_ok=True)
        return {"sessions_parsed": 0, "chunks_indexed": 0}

    monkeypatch.setattr("agentkb.chats.parser.build_chat_index", fake_build_chat_index)
    monkeypatch.setattr("agentkb.chats.parser.chat_index_is_stale", lambda _readable_dir, _index_dir: False)
    monkeypatch.setattr("agentkb.encoder.get_encoder", lambda: _FakeEncoder())
    monkeypatch.setattr("agentkb.encoder.DEFAULT_MODEL", "fake-model")
    monkeypatch.setattr("agentkb.search.merge_query_with_pattern", lambda query, pattern: query)
    monkeypatch.setattr("agentkb.search.search", lambda **kwargs: [])
    monkeypatch.setattr("agentkb.traceability.SearchTrace", _FakeTrace)

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        cli.search.callback(
            query="query",
            scope="chats",
            pattern=None,
            fixed=False,
            word=False,
            files_only=False,
            full_content=False,
            top_k=15,
            context_lines=6,
            json_output=True,
            include=(),
            exclude=(),
            exclude_dir=(),
            semantic_only=False,
        )

    assert seen["json_output"] is True
    assert '"results": []' in stdout.getvalue()
    assert "[agentkb] Chat index: fake rebuild" not in stdout.getvalue()
    assert "[agentkb] Chat index: fake rebuild" in stderr.getvalue()
