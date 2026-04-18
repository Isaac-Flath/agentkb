"""Tests for agentkb.traceability — search trace recording and retrieval.

Traceability records every search query and its intermediate results (semantic
ranking, keyword ranking, RRF fusion, final filtered results) into a SQLite
database. This is for evaluating and debugging search quality — you can look
at a past query and see exactly why a result ranked where it did: was it the
semantic score? the keyword match? did a filter remove a relevant result?
The traceability DB can also be synced to S3 for backup.
"""

from unittest.mock import patch
from pathlib import Path

from agentkb.traceability import SearchTrace, _connect, _db_path, recent_queries, get_trace


def _use_tmp_db(tmp_path):
    """Patch _db_path to use a temp directory."""
    return patch("agentkb.traceability._db_path", return_value=tmp_path / "trace.db")


def test_search_trace_save_and_retrieve(tmp_path):
    """A SearchTrace saves query params and pipeline stages to SQLite.

    The trace captures the full pipeline: what the user queried, what the
    semantic search returned, what keyword search returned, how RRF fused
    them, and what survived post-filtering. This lets you reconstruct
    exactly why a search returned what it did.
    """
    with _use_tmp_db(tmp_path):
        trace = SearchTrace(
            original_query="error handling",
            semantic_query="error handling async",
            pattern=r"async\s+",
            scope="wiki",
            top_k=10,
            collection="wiki",
            model_name="test-model",
        )
        # Simulate pipeline stages
        trace.semantic_ranking = [(1, 0.9), (2, 0.7), (3, 0.5)]
        trace.keyword_ranking = [(2, 15.0), (4, 10.0)]
        trace.rrf_ranking = [(2, 0.02), (1, 0.01), (3, 0.008), (4, 0.005)]
        trace.final_results = [
            {"doc_id": 2, "score": 0.7, "collection": "wiki", "file": "a.md",
             "line": 1, "name": "", "title": "", "section": "", "unit_type": "chunk",
             "content": "content", "raw_content": "raw", "tags": []},
        ]

        trace.save()

        # Verify via recent_queries
        queries = recent_queries(limit=5)
        assert len(queries) == 1
        assert queries[0]["original_query"] == "error handling"
        assert queries[0]["scope"] == "wiki"

        # Verify full trace retrieval
        full = get_trace(queries[0]["id"])
        assert full["query"]["semantic_query"] == "error handling async"
        assert len(full["semantic_results"]) == 3
        assert len(full["keyword_results"]) == 2
        assert len(full["rrf_results"]) == 4
        assert len(full["final_results"]) == 1


def test_recent_queries_empty(tmp_path):
    """Returns empty list when no traces have been saved."""
    with _use_tmp_db(tmp_path):
        assert recent_queries() == []


def test_get_trace_missing(tmp_path):
    """Returns empty dict for nonexistent query ID."""
    with _use_tmp_db(tmp_path):
        assert get_trace(999) == {}
