"""Search pipeline: PLAID semantic search, FTS5 keyword search, RRF fusion, result formatting."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field

import numpy as np

from agentkb.store import IndexStore


@dataclass
class SearchResult:
    """A single search result with provenance."""

    collection: str  # "wiki", "wiki:source", "chats"
    file: str
    line: int
    score: float
    name: str = ""
    unit_type: str = ""
    content: str = ""
    raw_content: str = ""
    title: str = ""
    section: str = ""
    tags: list[str] = field(default_factory=list)

    def format_terminal(self, context_lines: int = 6) -> str:
        """Format for human-readable terminal output."""
        tag = f"[{self.collection}]"
        loc = f"{self.file}:{self.line}"
        score = f"({self.score:.2f})"

        header = f"{tag} {loc}  {score}"

        # Show name/title
        if self.title and self.section:
            header += f"\n  {self.title} > {self.section}"
        elif self.name:
            header += f"\n  {self.name}"

        # Show content snippet
        lines = self.raw_content.split("\n") if self.raw_content else self.content.split("\n")
        snippet_lines = lines[:context_lines]
        snippet = "\n".join(f"  {l}" for l in snippet_lines)
        if len(lines) > context_lines:
            snippet += f"\n  ... ({len(lines) - context_lines} more lines)"

        return f"{header}\n{snippet}"

    def to_json(self) -> dict:
        """Format for JSON output."""
        d = {
            "collection": self.collection,
            "file": self.file,
            "line": self.line,
            "score": round(self.score, 4),
        }
        if self.name:
            d["name"] = self.name
        if self.unit_type:
            d["unit_type"] = self.unit_type
        if self.title:
            d["title"] = self.title
        if self.section:
            d["section"] = self.section
        if self.tags:
            d["tags"] = self.tags
        d["content"] = self.raw_content or self.content
        return d


RRF_K = 60.0


def rrf_fuse(
    semantic_ranking: list[tuple[int, float]],
    keyword_ranking: list[tuple[int, float]],
    alpha: float = 0.75,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion with alpha weighting (matches ColGREP/next-plaid).

    alpha controls balance: 1.0 = pure semantic, 0.0 = pure keyword.
    Default 0.75 weights semantic 3x higher than keyword.

    Each ranking is a list of (doc_id, score) sorted by score descending.
    Returns fused ranking as (doc_id, rrf_score) sorted descending.
    """
    rrf_scores: dict[int, float] = {}

    for rank, (doc_id, _score) in enumerate(semantic_ranking):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + alpha / (RRF_K + rank + 1)

    for rank, (doc_id, _score) in enumerate(keyword_ranking):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 - alpha) / (RRF_K + rank + 1)

    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return fused


def strip_regex_for_semantic(pattern: str) -> str:
    """Extract meaningful text from a regex pattern for semantic search.

    Strips metacharacters, character classes, quantifiers, and anchors.
    Converts alternation to spaces so the result can enrich a ColBERT query.

    Examples:
        "async\\s+fn" -> "async fn"
        "Result<.*>" -> "Result<>"
        "foo|bar" -> "foo bar"
    """
    # Turn escaped literals (\. \* etc) into the literal char, but drop
    # shorthand classes (\s \w \d \b \n \r \t) replacing them with space
    text = re.sub(r'\\([sSwWdDbBnrt])', ' ', pattern)
    text = re.sub(r'\\(.)', r'\1', text)
    # Drop character classes [...], quantifiers {n,m}, groups ()
    text = re.sub(r'\[(?:[^\]\\]|\\.)*\]', ' ', text)
    text = re.sub(r'\{[^}]*\}', '', text)
    text = re.sub(r'[().*+?^$]', '', text)
    # Alternation -> space
    text = text.replace('|', ' ')
    return ' '.join(text.split())


def merge_query_with_pattern(query: str, pattern: str) -> str:
    """Merge a semantic query with a sanitized regex pattern, deduplicating tokens.

    The pattern is stripped of regex metacharacters first. Tokens already present
    in the query are not repeated.
    """
    sanitized = strip_regex_for_semantic(pattern)
    if not sanitized:
        return query
    if not query:
        return sanitized

    query_tokens = {t.lower() for t in query.split()}
    new_tokens = [t for t in sanitized.split() if t.lower() not in query_tokens]
    if not new_tokens:
        return query
    return f"{query} {' '.join(new_tokens)}"


def _compile_pattern(
    pattern: str | None,
    fixed: bool = False,
    word: bool = False,
) -> re.Pattern | None:
    """Compile a regex pattern from CLI flags."""
    if not pattern:
        return None
    if fixed:
        pattern = re.escape(pattern)
    if word:
        pattern = rf"\b{pattern}\b"
    return re.compile(pattern)


def _matches_globs(filepath: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Check if filepath matches any of the given glob patterns."""
    for pat in patterns:
        if fnmatch.fnmatch(filepath, pat):
            return True
    return False


def search(
    store: IndexStore,
    query_embedding: np.ndarray,
    query_text: str,
    scope: str = "all",
    top_k: int = 3,
    pattern: str | None = None,
    fixed: bool = False,
    word: bool = False,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    semantic_only: bool = False,
    trace: "SearchTrace | None" = None,
) -> list[SearchResult]:
    """Run the full search pipeline: PLAID semantic + FTS5 keyword + RRF fusion.

    Args:
        store: The index store to search.
        query_embedding: ColBERT query embedding (num_tokens, dim).
        query_text: Original query text for keyword search.
        scope: "wiki", "chats", or "all".
        top_k: Number of results to return.
        pattern: Regex pattern to filter results (-e flag).
        fixed: Treat pattern as fixed string (-F flag).
        word: Add word boundaries to pattern (-w flag).
        include: Glob patterns — keep only matching files.
        exclude: Glob patterns — drop matching files.
        semantic_only: Skip keyword search, use semantic results only.
        trace: Optional SearchTrace to capture intermediate results.
    """
    collections = _scope_to_collections(scope)
    compiled_pattern = _compile_pattern(pattern, fixed, word)
    has_filters = compiled_pattern or include or exclude

    # Get subset of doc IDs for the requested scope
    subset_ids = None
    if scope != "all":
        subset_ids = []
        for coll in collections:
            subset_ids.extend(store.get_document_ids(collection=coll))
        if not subset_ids:
            return []

    # --- PLAID semantic search ---
    # Overfetch more when filters are active to compensate for discarded results
    overfetch = 5 if has_filters else 3
    fetch_k = top_k * overfetch
    semantic_ranking = store.semantic_search(
        query_embedding, top_k=fetch_k, subset_ids=subset_ids
    )

    if trace is not None:
        trace.semantic_ranking = list(semantic_ranking)

    # --- FTS5 keyword search (skip if semantic_only) ---
    keyword_ranking = []
    if not semantic_only:
        for coll in collections:
            try:
                results = store.keyword_search(query_text, collection=coll, limit=fetch_k)
                keyword_ranking.extend(results)
            except Exception as e:
                import sys
                print(f"[agentkb] Warning: keyword search failed for {coll}: {e}", file=sys.stderr)
        keyword_ranking.sort(key=lambda x: x[1], reverse=True)

    if trace is not None:
        trace.keyword_ranking = list(keyword_ranking)

    # --- RRF fusion ---
    if keyword_ranking:
        fused = rrf_fuse(semantic_ranking, keyword_ranking, alpha=0.75)
    else:
        fused = [(doc_id, score) for doc_id, score in semantic_ranking]

    if trace is not None:
        trace.rrf_ranking = list(fused)

    # --- Build results ---
    semantic_score_map = {doc_id: score for doc_id, score in semantic_ranking}

    results = []
    for doc_id, rrf_score in fused:
        doc = store.get_document_by_id(doc_id)
        if not doc:
            continue

        # --- Post-filters ---
        # Glob include/exclude on file path
        if include and not _matches_globs(doc.file, include):
            continue
        if exclude and _matches_globs(doc.file, exclude):
            continue

        # Regex pattern match on content
        if compiled_pattern:
            text = doc.raw_content or doc.content
            if not compiled_pattern.search(text):
                continue

        result = SearchResult(
            collection=doc.collection,
            file=doc.file,
            line=doc.line,
            score=semantic_score_map.get(doc_id, 0.0),
            name=doc.name,
            unit_type=doc.unit_type,
            content=doc.content,
            raw_content=doc.raw_content,
            title=doc.title,
            section=doc.section,
            tags=json.loads(doc.tags) if doc.tags else [],
        )
        results.append(result)

        if trace is not None:
            trace.final_results.append({
                "doc_id": doc_id,
                "score": result.score,
                "collection": doc.collection,
                "file": doc.file,
                "line": doc.line,
                "name": doc.name,
                "title": doc.title,
                "section": doc.section,
                "unit_type": doc.unit_type,
                "content": doc.content,
                "raw_content": doc.raw_content,
                "tags": json.loads(doc.tags) if doc.tags else [],
            })

        if len(results) >= top_k:
            break

    return results


def merge_multi_collection(
    result_lists: list[list[SearchResult]],
    top_k: int = 3,
) -> list[SearchResult]:
    """Merge results from multiple stores using RRF.

    Scores are not directly comparable across collections (different document lengths,
    different structured text formats), so rank fusion is more robust than raw score merging.
    Duplicate results (same file + line) across stores are merged, not duplicated.
    """
    rrf_scores: dict[tuple, float] = {}
    result_map: dict[tuple, SearchResult] = {}

    for results in result_lists:
        for rank, result in enumerate(results):
            key = (result.file, result.line)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            result_map[key] = result

    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [result_map[key] for key, _ in ranked[:top_k]]


def _scope_to_collections(scope: str) -> list[str]:
    match scope:
        case "wiki":
            return ["wiki", "wiki:source"]
        case "wiki:notes":
            return ["wiki"]
        case "wiki:source":
            return ["wiki:source"]
        case "chats":
            return ["chats"]
        case "communications":
            return ["communications"]
        case _:
            return ["wiki", "wiki:source", "chats"]
