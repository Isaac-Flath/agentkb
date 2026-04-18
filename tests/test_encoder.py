"""Tests for agentkb.encoder — ColBERT model loading and encoding.

encoder.py wraps pylate's ColBERT model for generating multi-vector embeddings.
Unlike traditional embeddings (one vector per document), ColBERT produces one
vector per token. This enables late-interaction scoring in PLAID — query tokens
are matched against document tokens individually, which gives much better
retrieval quality for knowledge-base-style content than single-vector models.

The encoder is lazily loaded (not initialized until first use) to keep CLI
startup fast — importing pylate and loading the model takes ~2s, and most
CLI commands (like `agentkb status`) don't need it.

These tests load the real model so they verify actual behavior, not mocks.
"""

import numpy as np

from agentkb.encoder import get_encoder, ColBERTEncoder, DEFAULT_MODEL


# get_encoder uses a module-level cache so the model is only loaded once per
# process. This matters because model loading is expensive (~2s), and a single
# search command calls encode_query once but the indexer calls encode_documents
# many times — they should all share the same model instance.
def test_get_encoder_returns_cached_instance():
    """get_encoder() returns the same instance on repeated calls (singleton cache)."""
    e1 = get_encoder()
    e2 = get_encoder()
    assert e1 is e2


def test_get_encoder_default_model():
    """Default encoder uses the GTE-ModernColBERT model."""
    e = get_encoder()
    assert e.model_name == DEFAULT_MODEL


# encode_query produces a 2D array: (num_query_tokens, embedding_dim).
# ColBERT queries typically have more tokens than the raw text because the
# model pads queries with [MASK] tokens for better retrieval.
def test_encode_query_shape():
    """encode_query returns a 2D numpy array: (num_tokens, embedding_dim)."""
    e = get_encoder()
    result = e.encode_query("how do I rebase in git")
    assert isinstance(result, np.ndarray)
    assert result.ndim == 2
    assert result.shape[0] > 0   # at least 1 token
    assert result.shape[1] > 0   # embedding dim > 0
    assert result.dtype == np.float32


# encode_documents produces a list of 2D arrays, one per document. Each
# document's array has a different number of tokens (longer docs = more tokens),
# but the same embedding dimension. These per-document arrays are what PLAID
# indexes for fast late-interaction retrieval.
def test_encode_documents_shape():
    """encode_documents returns a list of 2D arrays, one per document."""
    e = get_encoder()
    texts = ["Git rebasing guide", "Python asyncio patterns"]
    results = e.encode_documents(texts, batch_size=2)
    assert len(results) == 2
    for emb in results:
        assert isinstance(emb, np.ndarray)
        assert emb.ndim == 2
        assert emb.dtype == np.float32


def test_encode_documents_single():
    """Works with a single document."""
    e = get_encoder()
    results = e.encode_documents(["just one document"])
    assert len(results) == 1


def test_dim_property():
    """The dim property returns the embedding dimension (matches encode output)."""
    e = get_encoder()
    dim = e.dim
    query_emb = e.encode_query("test")
    assert query_emb.shape[1] == dim
