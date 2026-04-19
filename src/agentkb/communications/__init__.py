"""Communications store: imported messages, posts, and transcripts from human platforms."""

from __future__ import annotations

from agentkb.communications.parser import build_communications_index, communications_index_is_stale
from agentkb.config import paths
from agentkb.output import echo_status
from agentkb.store import IndexStore

# Register all communications sources on import
import agentkb.communications.sources.x  # noqa: F401


NOT_READY_MESSAGE = (
    "[agentkb] No communications found. Run `agentkb store communications index` first."
)


def _render_from_raw() -> tuple[object, object, object]:
    """Re-render readable markdown from existing raw; returns (raw_dir, readable_dir, index_dir)."""
    from agentkb.communications.sources import SOURCES

    comms_dir = paths.communications_dir()
    raw_dir = comms_dir / "raw"
    readable_dir = comms_dir / "readable"
    index_dir = comms_dir / ".index"

    if raw_dir.exists():
        for src in SOURCES.values():
            src_raw = raw_dir / src.name
            if src_raw.exists():
                try:
                    src.render(src_raw, readable_dir)
                except Exception:
                    pass

    return raw_dir, readable_dir, index_dir


def ensure_search_store(*, json_output: bool = False) -> IndexStore | None:
    """Re-render readable markdown from existing raw (no API fetch) and refresh the index.

    Does NOT fetch from external APIs — users fetch explicitly via
    ``agentkb store communications fetch`` or ``agentkb store communications index``.
    """
    _, readable_dir, index_dir = _render_from_raw()

    if not readable_dir.exists():
        return None

    if not index_dir.exists():
        echo_status("[agentkb] Building communications index...", json_output=json_output)
        build_communications_index(readable_dir, index_dir, json_output=json_output)
    elif communications_index_is_stale(readable_dir, index_dir):
        build_communications_index(readable_dir, index_dir, tracked_only=True, json_output=json_output)

    return IndexStore(index_dir) if index_dir.exists() else None


def reindex(*, model: str | None = None, fetch: bool = True) -> dict:
    """Optionally fetch from source APIs, then re-render and rebuild the index.

    Per-source fetch failures are logged to stderr and don't abort the run.
    Returns :func:`build_communications_index` stats (or ``{}`` if nothing to index).
    """
    from agentkb.communications.sources import SOURCES

    comms_dir = paths.communications_dir()
    raw_dir = comms_dir / "raw"

    if fetch:
        import click  # click is already a dep; use it for consistent CLI messaging
        raw_dir.mkdir(parents=True, exist_ok=True)
        for src in SOURCES.values():
            src_raw = raw_dir / src.name
            if not src_raw.exists():
                continue
            try:
                stats = src.fetch(src_raw)
                if stats.get("fetched"):
                    click.echo(f"[agentkb] {src.name} fetch: {stats['fetched']} new")
                for err in stats.get("errors", []) or []:
                    click.echo(f"  ! {src.name}: {err}", err=True)
            except Exception as e:
                click.echo(f"[agentkb] {src.name} fetch failed: {e}", err=True)

    _, readable_dir, index_dir = _render_from_raw()
    if not readable_dir.exists():
        return {}
    return build_communications_index(readable_dir, index_dir, model_name=model)


def status_lines() -> list[str]:
    """Return the ``agentkb status`` output for this store."""
    from agentkb.communications.sources.x import load_handles

    comms_dir = paths.communications_dir()
    index_dir = comms_dir / ".index"
    raw_dir = comms_dir / "raw"

    handle_count = 0
    if (raw_dir / "x" / "_handles.json").exists():
        handle_count = len(load_handles(raw_dir / "x"))

    if index_dir.exists():
        store = IndexStore(index_dir)
        if store.exists():
            suffix = f" ({handle_count} X handles)" if handle_count else ""
            line = (
                f"  Communications: {store.document_count()} chunks across "
                f"{store.file_count()} files{suffix}"
            )
            store.close()
            return [line]

    if handle_count:
        return [f"  Communications: {handle_count} X handles tracked, not indexed (run `agentkb store communications index`)"]
    return ["  Communications: not configured (run `agentkb store communications x add-handle <handle>`)"]
