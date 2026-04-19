"""ColBERT encoding: load model and encode documents/queries into multi-vector embeddings."""

from __future__ import annotations

import numpy as np

DEFAULT_MODEL = "lightonai/GTE-ModernColBERT-v1"

# Encoder cache — one instance per model name
_encoder_cache: dict[str, "ColBERTEncoder"] = {}


def get_encoder(model_name: str | None = None) -> "ColBERTEncoder":
    """Get (or create) the ColBERT encoder."""
    if model_name is None:
        model_name = DEFAULT_MODEL
    if model_name not in _encoder_cache:
        _encoder_cache[model_name] = ColBERTEncoder(model_name=model_name)
    return _encoder_cache[model_name]


class ColBERTEncoder:
    """Wraps a ColBERT model for encoding documents and queries.

    Lazily loads the model on first use to avoid slow imports at CLI startup.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is not None:
            return

        from pylate import models

        self._model = models.ColBERT(
            model_name_or_path=self.model_name,
            device="cpu",  # safe default, auto-detect later
        )

    def encode_documents(self, texts: list[str], batch_size: int = 32) -> list[np.ndarray]:
        """Encode document texts into per-token embeddings.

        Returns a list of numpy arrays, each of shape (num_tokens, embedding_dim).
        """
        self._load()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            is_query=False,
            show_progress_bar=True,
        )
        return [np.array(emb, dtype=np.float32) for emb in embeddings]

    def encode_query(self, query: str) -> np.ndarray:
        """Encode a single query into per-token embeddings.

        Returns a numpy array of shape (num_tokens, embedding_dim).
        """
        self._load()
        embeddings = self._model.encode(
            [query],
            batch_size=1,
            is_query=True,
            show_progress_bar=False,
        )
        return np.array(embeddings[0], dtype=np.float32)

    @property
    def dim(self) -> int:
        """Embedding dimension."""
        self._load()
        return self._model.get_sentence_embedding_dimension()
