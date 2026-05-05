"""Index storage: SQLite metadata + FTS5 keyword search + PLAID vector index."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Document:
    """A document stored in the index."""

    id: int
    collection: str  # "wiki", "wiki:source", "chats"
    file: str
    line: int
    name: str
    unit_type: str  # function, class, method, chunk, etc.
    content: str  # structured text that was embedded
    raw_content: str  # original code/markdown
    title: str = ""  # for wiki pages
    section: str = ""  # for Wiki chunks
    tags: str = "[]"  # JSON array


class IndexStore:
    """Manages the on-disk index: SQLite for metadata/FTS and PLAID for vector search."""

    def __init__(self, index_dir: Path, content_root: Path | None = None):
        self.index_dir = index_dir
        self.content_root = content_root.expanduser().resolve() if content_root else None
        self.db_path = index_dir / "metadata.db"
        self.plaid_dir = index_dir / "plaid"
        self.state_path = index_dir / "state.json"
        self._conn: sqlite3.Connection | None = None
        self._plaid_index = None

    def exists(self) -> bool:
        return self.db_path.exists()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def create(self):
        """Create a fresh index store."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                file TEXT NOT NULL,
                line INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL DEFAULT '',
                unit_type TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                raw_content TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                name, content, file, title, section,
                content='documents',
                content_rowid='id',
                tokenize='trigram'
            );

            CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, name, content, file, title, section)
                VALUES (new.id, new.name, new.content, new.file, new.title, new.section);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, name, content, file, title, section)
                VALUES ('delete', old.id, old.name, old.content, old.file, old.title, old.section);
            END;
        """)
        conn.commit()

    def clear(self):
        """Remove all documents and embeddings."""
        conn = self._connect()
        conn.execute("DELETE FROM documents")
        conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        conn.commit()
        # Clear PLAID index
        if self.plaid_dir.exists():
            shutil.rmtree(self.plaid_dir)
        self._plaid_index = None

    def add_documents(self, docs: list[dict]) -> list[int]:
        """Insert documents into the metadata store. Returns their IDs."""
        conn = self._connect()
        ids = []
        for doc in docs:
            cursor = conn.execute(
                """INSERT INTO documents (collection, file, line, name, unit_type, content, raw_content, title, section, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc["collection"],
                    doc["file"],
                    doc.get("line", 1),
                    doc.get("name", ""),
                    doc.get("unit_type", ""),
                    doc["content"],
                    doc.get("raw_content", ""),
                    doc.get("title", ""),
                    doc.get("section", ""),
                    json.dumps(doc.get("tags", [])),
                ),
            )
            ids.append(cursor.lastrowid)
        conn.commit()
        return ids

    def _load_plaid_index(self):
        """Load the PLAID index from disk."""
        if self._plaid_index is not None:
            return

        from pylate import indexes

        self._plaid_index = indexes.PLAID(
            index_folder=str(self.index_dir),
            index_name="plaid",
            override=False,
        )

    def semantic_search(self, query_embedding: np.ndarray, top_k: int = 50, subset_ids: list[int] | None = None) -> list[tuple[int, float]]:
        """Run PLAID semantic search. Returns list of (doc_id, score).

        Args:
            query_embedding: ColBERT query embedding (num_tokens, dim)
            top_k: Max results to return
            subset_ids: Optional list of doc IDs to restrict search to
        """
        self._load_plaid_index()

        subset = None
        if subset_ids is not None:
            subset = [str(did) for did in subset_ids]

        results = self._plaid_index(
            [query_embedding],
            k=top_k,
            subset=[subset] if subset else None,
        )

        # results is [[{"id": str, "score": float}, ...]]
        return [(int(r["id"]), r["score"]) for r in results[0]]

    def get_document_ids(self, collection: str | None = None) -> list[int]:
        """Get document IDs, optionally filtered by collection."""
        conn = self._connect()
        if collection:
            rows = conn.execute(
                "SELECT id FROM documents WHERE collection = ? ORDER BY id",
                (collection,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id FROM documents ORDER BY id").fetchall()
        return [row["id"] for row in rows]

    def get_document_by_id(self, doc_id: int) -> Document | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return Document(**dict(row)) if row else None

    def resolve_file_path(self, file: str) -> str:
        """Resolve an indexed document path to an absolute filesystem path."""
        path = Path(file).expanduser()
        if path.is_absolute():
            return str(path.resolve(strict=False))
        if self.content_root is not None:
            return str((self.content_root / path).resolve(strict=False))
        return str(path.resolve(strict=False))

    def keyword_search(self, query: str, collection: str | None = None, limit: int = 50) -> list[tuple[int, float]]:
        """Run FTS5 keyword search. Returns list of (doc_id, bm25_score)."""
        query = sanitize_fts5_query(query)
        if not query:
            return []

        conn = self._connect()

        if collection:
            rows = conn.execute(
                """SELECT d.id, rank
                   FROM documents_fts f
                   JOIN documents d ON d.id = f.rowid
                   WHERE documents_fts MATCH ? AND d.collection = ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, collection, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT rowid as id, rank
                   FROM documents_fts
                   WHERE documents_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()

        # FTS5 rank is negative (lower is better), convert to positive score
        return [(row["id"], -row["rank"]) for row in rows]

    def document_count(self, collection: str | None = None) -> int:
        conn = self._connect()
        if collection:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM documents WHERE collection = ?",
                (collection,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM documents").fetchone()
        return row["cnt"]

    def file_count(self, collection: str | None = None) -> int:
        conn = self._connect()
        if collection:
            row = conn.execute(
                "SELECT COUNT(DISTINCT file) as cnt FROM documents WHERE collection = ?",
                (collection,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(DISTINCT file) as cnt FROM documents").fetchone()
        return row["cnt"]

    def delete_documents_by_file(self, files: set[str]):
        """Delete all documents whose file field matches any of the given paths."""
        if not files:
            return
        conn = self._connect()
        for f in files:
            conn.execute("DELETE FROM documents WHERE file = ?", (f,))
        conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        conn.commit()

    def append_plaid_index(self, doc_ids: list[int], embeddings: list):
        """Add new documents to an existing PLAID index.

        If no PLAID index exists yet, creates one. If it exists,
        loads it and appends the new documents.
        """
        from pylate import indexes

        if self.plaid_dir.exists():
            # Load existing index and add to it
            index = indexes.PLAID(
                index_folder=str(self.index_dir),
                index_name="plaid",
                override=False,
            )
        else:
            # Create new index
            index = indexes.PLAID(
                index_folder=str(self.index_dir),
                index_name="plaid",
                override=True,
            )

        str_ids = [str(did) for did in doc_ids]
        index.add_documents(
            documents_ids=str_ids,
            documents_embeddings=embeddings,
        )
        self._plaid_index = index

    # --- Incremental indexing state ---

    def load_state(self) -> dict:
        """Load file hash state for incremental indexing."""
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {}

    def save_state(self, state: dict):
        self.state_path.write_text(json.dumps(state, indent=2))

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
        self._plaid_index = None



FTS5_OPERATORS = {"AND", "OR", "NOT", "NEAR"}


def sanitize_fts5_query(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH syntax.

    Quotes each token to preserve special characters (C++, node.js, .env)
    and skips FTS5 boolean operators. Works with both word and trigram tokenizers.
    """
    tokens = []
    for word in query.split():
        # Strip non-alphanumeric from edges only
        trimmed = word.strip("()[]{}!@#$%^&*;:,<>?/\\|`~=")
        if not trimmed:
            continue
        if trimmed.upper() in FTS5_OPERATORS:
            continue
        # Escape internal double quotes and wrap in quotes
        escaped = trimmed.replace('"', '""')
        tokens.append(f'"{escaped}"')
    return " ".join(tokens)
