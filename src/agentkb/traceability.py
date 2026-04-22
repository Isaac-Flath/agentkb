"""Search traceability: capture queries, intermediate rankings, and final results for evals."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from agentkb.config import paths


DB_NAME = "traceability.db"


def _db_path() -> Path:
    return paths.agentkb_home() / DB_NAME


def _connect() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            original_query TEXT NOT NULL,
            semantic_query TEXT NOT NULL,
            pattern TEXT,
            fixed INTEGER NOT NULL DEFAULT 0,
            word INTEGER NOT NULL DEFAULT 0,
            scope TEXT NOT NULL,
            top_k INTEGER NOT NULL,
            include TEXT NOT NULL DEFAULT '[]',
            exclude TEXT NOT NULL DEFAULT '[]',
            semantic_only INTEGER NOT NULL DEFAULT 0,
            model_name TEXT NOT NULL DEFAULT '',
            collection TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS stage_results (
            query_id INTEGER NOT NULL REFERENCES queries(id),
            stage TEXT NOT NULL,
            rank INTEGER NOT NULL,
            doc_id INTEGER NOT NULL,
            score REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (query_id, stage, rank)
        );
    """)
    conn.commit()


@dataclass
class SearchTrace:
    """Accumulates data from each stage of the search pipeline."""

    # Query params (set by caller before search)
    original_query: str = ""
    semantic_query: str = ""
    pattern: str | None = None
    fixed: bool = False
    word: bool = False
    scope: str = ""
    top_k: int = 3
    include: tuple[str, ...] | list[str] = ()
    exclude: tuple[str, ...] | list[str] = ()
    semantic_only: bool = False
    model_name: str = ""
    collection: str = ""  # which store/collection this trace is from

    # Intermediate results (set by search pipeline)
    semantic_ranking: list[tuple[int, float]] = field(default_factory=list)
    keyword_ranking: list[tuple[int, float]] = field(default_factory=list)
    rrf_ranking: list[tuple[int, float]] = field(default_factory=list)

    # Final results (set after post-filtering)
    final_results: list[dict] = field(default_factory=list)

    def save(self):
        """Persist this trace to the traceability database."""
        conn = _connect()
        try:
            _save_trace(conn, self)
            conn.commit()
        finally:
            conn.close()


def _save_trace(conn: sqlite3.Connection, trace: SearchTrace):
    """Insert a complete search trace into the database."""
    ts = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        """INSERT INTO queries
           (timestamp, original_query, semantic_query, pattern, fixed, word,
            scope, top_k, include, exclude, semantic_only, model_name, collection)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ts,
            trace.original_query,
            trace.semantic_query,
            trace.pattern,
            int(trace.fixed),
            int(trace.word),
            trace.scope,
            trace.top_k,
            json.dumps(list(trace.include)),
            json.dumps(list(trace.exclude)),
            int(trace.semantic_only),
            trace.model_name,
            trace.collection,
        ),
    )
    query_id = cursor.lastrowid

    # Build cross-reference maps for RRF metadata
    semantic_rank_map = {doc_id: rank for rank, (doc_id, _) in enumerate(trace.semantic_ranking)}
    keyword_rank_map = {doc_id: rank for rank, (doc_id, _) in enumerate(trace.keyword_ranking)}

    # Save all pipeline stages in one loop
    stages = [
        ("semantic", trace.semantic_ranking, lambda doc_id, score: {}),
        ("keyword", trace.keyword_ranking, lambda doc_id, score: {}),
        ("rrf", trace.rrf_ranking, lambda doc_id, score: {
            "semantic_rank": semantic_rank_map.get(doc_id),
            "keyword_rank": keyword_rank_map.get(doc_id),
        }),
    ]
    for stage_name, rankings, meta_fn in stages:
        for rank, (doc_id, score) in enumerate(rankings):
            conn.execute(
                "INSERT INTO stage_results (query_id, stage, rank, doc_id, score, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (query_id, stage_name, rank, doc_id, score, json.dumps(meta_fn(doc_id, score))),
            )

    # Final results carry richer metadata
    for rank, result in enumerate(trace.final_results):
        conn.execute(
            "INSERT INTO stage_results (query_id, stage, rank, doc_id, score, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (query_id, "final", rank, result.get("doc_id", 0), result.get("score", 0.0), json.dumps(result)),
        )


def recent_queries(limit: int = 20) -> list[dict]:
    """Fetch recent queries for inspection."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM queries ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_trace(query_id: int) -> dict:
    """Fetch a full trace (query + all stage results)."""
    conn = _connect()
    try:
        query = conn.execute(
            "SELECT * FROM queries WHERE id = ?", (query_id,)
        ).fetchone()
        if not query:
            return {}

        result = {"query": dict(query)}
        for stage in ("semantic", "keyword", "rrf", "final"):
            rows = conn.execute(
                "SELECT * FROM stage_results WHERE query_id = ? AND stage = ? ORDER BY rank",
                (query_id, stage),
            ).fetchall()
            result[f"{stage}_results"] = [dict(r) for r in rows]
        return result
    finally:
        conn.close()


# --- S3 backup ---


def _s3_config() -> tuple[str, str]:
    """Return (bucket, key) from settings. Raises if not configured."""
    from agentkb.config import Settings
    s = Settings()
    bucket = s.get("traceability_s3_bucket")
    key = s.get("traceability_s3_key")
    if not bucket:
        raise RuntimeError(
            "S3 bucket not configured. Set with:\n"
            '  agentkb settings set traceability_s3_bucket "your-bucket-name"'
        )
    return bucket, key


def push_s3(verbose: bool = False) -> str:
    """Upload traceability.db to S3. Returns status string."""
    bucket, key = _s3_config()
    db = _db_path()
    if not db.exists():
        return "skipped (no local db)"

    client = boto3.client("s3")
    client.upload_file(str(db), bucket, key)
    if verbose:
        size_mb = db.stat().st_size / (1024 * 1024)
        return f"ok ({size_mb:.1f} MB -> s3://{bucket}/{key})"
    return "ok"


def pull_s3(verbose: bool = False) -> str:
    """Download traceability.db from S3. Returns status string."""
    bucket, key = _s3_config()
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    client = boto3.client("s3")
    try:
        client.download_file(bucket, key, str(db))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            return "skipped (not in S3 yet)"
        raise
    if verbose:
        size_mb = db.stat().st_size / (1024 * 1024)
        return f"ok ({size_mb:.1f} MB from s3://{bucket}/{key})"
    return "ok"
