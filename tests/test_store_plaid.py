"""Tests for IndexStore PLAID vector indexing — build, search, append.

PLAID (Performance-optimized Late Interaction using Approximate Decomposition)
is the vector index that makes ColBERT search fast. Instead of brute-force
comparing query tokens against every document token, PLAID compresses document
embeddings using k-means centroids and quantization, then does approximate
nearest-neighbor search. This is what lets agentkb search thousands of chunks
in milliseconds.

These tests use the real ColBERT encoder to generate embeddings and build
real PLAID indexes, verifying the full encode -> index -> search pipeline.
"""

import numpy as np

from agentkb.encoder import get_encoder
from agentkb.store import IndexStore


def _build_test_store(tmp_path, docs_with_text):
    """Helper: create a store, add documents, encode them, build PLAID index.

    Args:
        docs_with_text: list of (doc_dict, text_for_embedding) tuples
    Returns:
        (store, doc_ids, embeddings)
    """
    store = IndexStore(tmp_path / "idx")
    store.create()

    docs = [d for d, _ in docs_with_text]
    texts = [t for _, t in docs_with_text]

    doc_ids = store.add_documents(docs)

    encoder = get_encoder()
    embeddings = encoder.encode_documents(texts)

    return store, doc_ids, embeddings


def test_build_plaid_index(tmp_path):
    """build_plaid_index creates a PLAID index directory on disk."""
    store, doc_ids, embeddings = _build_test_store(tmp_path, [
        ({"collection": "wiki", "file": "a.md", "content": "Git basics"}, "Git basics and commands"),
        ({"collection": "wiki", "file": "b.md", "content": "Python tips"}, "Python programming tips"),
    ])

    store.build_plaid_index(doc_ids, embeddings)
    assert store.plaid_dir.exists()
    store.close()


# This is the core semantic search test: encode a few topically distinct
# documents, build the PLAID index, then query for one topic and verify it
# ranks the right document first. This validates that the full pipeline
# (ColBERT encoding -> PLAID indexing -> late-interaction scoring) works.
def test_semantic_search_returns_results(tmp_path):
    """semantic_search finds documents by vector similarity."""
    store, doc_ids, embeddings = _build_test_store(tmp_path, [
        ({"collection": "wiki", "file": "git.md", "content": "Git rebase and merge strategies"},
         "Git rebase and merge strategies"),
        ({"collection": "wiki", "file": "python.md", "content": "Python asyncio event loop"},
         "Python asyncio event loop"),
        ({"collection": "wiki", "file": "rust.md", "content": "Rust ownership and borrowing"},
         "Rust ownership and borrowing"),
    ])
    store.build_plaid_index(doc_ids, embeddings)

    encoder = get_encoder()
    query_emb = encoder.encode_query("git rebasing")

    results = store.semantic_search(query_emb, top_k=3)
    assert len(results) > 0
    # Results are (doc_id, score) tuples
    result_ids = [doc_id for doc_id, _ in results]
    result_scores = [score for _, score in results]
    # Git doc should rank highest for a git query
    assert result_ids[0] == doc_ids[0]
    # Scores should be positive
    assert all(s > 0 for s in result_scores)
    store.close()


# subset_ids is how scope filtering works in the search pipeline. When you
# search with --scope wiki, the pipeline gets all wiki doc IDs and passes
# them as subset_ids to PLAID. This restricts the search to only those
# documents without needing separate indexes per collection.
def test_semantic_search_with_subset(tmp_path):
    """subset_ids restricts search to specific documents."""
    store, doc_ids, embeddings = _build_test_store(tmp_path, [
        ({"collection": "wiki", "file": "a.md", "content": "Git guide"}, "Git rebase guide"),
        ({"collection": "chats", "file": "b.md", "content": "Git chat"}, "Git discussion in chat"),
        ({"collection": "wiki", "file": "c.md", "content": "Python"}, "Python programming"),
    ])
    store.build_plaid_index(doc_ids, embeddings)

    encoder = get_encoder()
    query_emb = encoder.encode_query("git")

    # Only search within doc_ids[1:] (exclude the first doc)
    results = store.semantic_search(query_emb, top_k=3, subset_ids=doc_ids[1:])
    result_ids = [doc_id for doc_id, _ in results]
    assert doc_ids[0] not in result_ids
    store.close()


# append_plaid_index is used for incremental indexing. When new wiki pages are
# added or chat sessions are indexed, their embeddings are appended to the
# existing PLAID index rather than rebuilding from scratch. This is much faster
# for large indexes.
def test_append_plaid_index(tmp_path):
    """append_plaid_index adds new documents to an existing PLAID index."""
    encoder = get_encoder()

    store = IndexStore(tmp_path / "idx")
    store.create()

    # First batch — need multiple docs for PLAID k-means to work
    ids1 = store.add_documents([
        {"collection": "wiki", "file": "a.md", "content": "Git rebase strategies"},
        {"collection": "wiki", "file": "b.md", "content": "Rust ownership model"},
    ])
    emb1 = encoder.encode_documents(["Git rebase strategies", "Rust ownership model"])
    store.build_plaid_index(ids1, emb1)

    # Append second batch
    ids2 = store.add_documents([
        {"collection": "wiki", "file": "c.md", "content": "Python asyncio patterns"},
        {"collection": "wiki", "file": "d.md", "content": "JavaScript promises"},
    ])
    emb2 = encoder.encode_documents(["Python asyncio patterns", "JavaScript promises"])
    store.append_plaid_index(ids2, emb2)

    # Search should find documents from both batches
    query_emb = encoder.encode_query("Python")
    results = store.semantic_search(query_emb, top_k=5)
    result_ids = [doc_id for doc_id, _ in results]
    assert ids2[0] in result_ids  # Python doc from second batch should be found
    store.close()


def test_append_plaid_creates_if_missing(tmp_path):
    """append_plaid_index creates a new index if none exists yet.

    The wiki and chat indexers both use append_plaid_index (not build_plaid_index)
    so this path handles the initial index creation too.
    """
    encoder = get_encoder()
    store = IndexStore(tmp_path / "idx")
    store.create()

    # Need multiple docs for PLAID k-means clustering
    ids = store.add_documents([
        {"collection": "wiki", "file": "a.md", "content": "First new document"},
        {"collection": "wiki", "file": "b.md", "content": "Second new document"},
    ])
    emb = encoder.encode_documents(["First new document", "Second new document"])

    # No build_plaid_index first — append should create it
    assert not store.plaid_dir.exists()
    store.append_plaid_index(ids, emb)
    assert store.plaid_dir.exists()
    store.close()
