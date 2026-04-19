"""Wiki store: markdown pages + ingested sources, indexed with ColBERT + FTS5."""

from __future__ import annotations

from agentkb.config import paths
from agentkb.output import echo_status
from agentkb.store import IndexStore
from agentkb.wiki.manager import KnowledgeBase
from agentkb.wiki.parser import build_wiki_index, wiki_index_is_stale


NOT_READY_MESSAGE = "[agentkb] No wiki found. Run `agentkb store wiki init` first."


def ensure_search_store(*, json_output: bool = False) -> IndexStore | None:
    """Make sure the wiki index is fresh and return an :class:`IndexStore` for searching."""
    wiki_path = paths.wiki_dir()
    if not wiki_path.exists():
        return None

    index_dir = wiki_path / ".index"
    if not index_dir.exists() or wiki_index_is_stale(wiki_path, index_dir):
        echo_status("[agentkb] Updating Wiki index...", json_output=json_output)
        build_wiki_index(wiki_path, index_dir, json_output=json_output)

    return IndexStore(index_dir)


def reindex(*, model: str | None = None) -> dict:
    """Rebuild the wiki index from disk. Returns :func:`build_wiki_index` stats (or ``{}`` if no wiki)."""
    wiki_path = paths.wiki_dir()
    if not (wiki_path.exists() and (wiki_path / "wiki").exists()):
        return {}
    return build_wiki_index(wiki_path, wiki_path / ".index", model_name=model)


def status_lines() -> list[str]:
    """Return the ``agentkb status`` output for this store."""
    wiki_path = paths.wiki_dir()
    if not wiki_path.exists():
        return ["  Wiki: not initialized (run `agentkb store wiki init`)"]

    stats = KnowledgeBase(wiki_path).status()
    lines = [f"  Wiki: {stats['wiki_pages']} pages, {stats['sources']} sources"]

    index_dir = wiki_path / ".index"
    if index_dir.exists():
        store = IndexStore(index_dir)
        if store.exists():
            lines.append(f"  Wiki index: {store.document_count()} chunks indexed")
            store.close()
    return lines
