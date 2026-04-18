from __future__ import annotations

import json as json_mod
from datetime import datetime, timezone
from pathlib import Path

import click

from agentkb.config import paths
from agentkb.utils import parse_frontmatter, parse_time_filter, strip_frontmatter


def _ensure_gitignore() -> None:
    """Write .gitignore at the store root so `.index/` stays out of git sync.

    The index is ~10x the size of raw+readable and is fully reproducible from
    them locally, so it should never be pushed to a sync remote.
    """
    comms = paths.communications_dir()
    comms.mkdir(parents=True, exist_ok=True)
    gi = comms / ".gitignore"
    if not gi.exists():
        gi.write_text(".index/\n")


def _raw_dir() -> Path:
    _ensure_gitignore()
    return paths.communications_dir() / "raw"


def _readable_dir() -> Path:
    _ensure_gitignore()
    return paths.communications_dir() / "readable"


def _index_dir() -> Path:
    return paths.communications_dir() / ".index"


def _x_raw_dir() -> Path:
    return _raw_dir() / "x"


@click.group()
def communications():
    """Communications store: X posts, messages, transcripts."""
    pass


# --- X source subcommands ---


@communications.group()
def x():
    """X (Twitter) source operations."""
    pass


@x.command("add-handle")
@click.argument("handles", nargs=-1, required=True)
def x_add_handle(handles):
    """Register one or more X handles to track.

    Resolves each handle via the X API (requires X_BEARER_TOKEN) and stores
    the user_id in the handles manifest so subsequent fetches can use the
    cheaper timeline endpoint directly.

    Usage: agentkb communications x add-handle karpathy mariozechner
    """
    from agentkb.communications.sources.x import add_handle

    raw_dir = _x_raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)

    for h in handles:
        clean = h.lstrip("@").strip()
        try:
            entry = add_handle(raw_dir, clean)
            click.echo(f"[agentkb] @{clean}: user_id={entry['user_id']} ({entry.get('name', '')})")
        except Exception as e:
            click.echo(f"[agentkb] Failed to add @{clean}: {e}", err=True)


@x.command("remove-handle")
@click.argument("handle")
def x_remove_handle(handle):
    """Remove an X handle from the tracked list (does not delete stored data)."""
    from agentkb.communications.sources.x import remove_handle

    clean = handle.lstrip("@").strip()
    if remove_handle(_x_raw_dir(), clean):
        click.echo(f"[agentkb] Removed @{clean}")
    else:
        click.echo(f"[agentkb] @{clean} not in manifest")


@x.command("list-handles")
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
def x_list_handles(json_output):
    """Show tracked X handles."""
    from agentkb.communications.sources.x import load_handles

    handles = load_handles(_x_raw_dir())

    if json_output:
        click.echo(json_mod.dumps({"handles": handles}, indent=2))
        return

    if not handles:
        click.echo("[agentkb] No X handles tracked. Use `agentkb store communications x add-handle <handle>`.")
        return
    for name in sorted(handles):
        entry = handles[name]
        click.echo(f"  @{name} — {entry.get('name', '')} (id={entry['user_id']})")


@x.command("fetch")
@click.option("--handle", help="Only fetch this one handle")
def x_fetch(handle):
    """Pull new tweets for tracked handles into the raw store."""
    from agentkb.communications.sources.x import fetch, fetch_handle_tweets

    raw_dir = _x_raw_dir()
    if handle:
        clean = handle.lstrip("@").strip()
        try:
            stats = fetch_handle_tweets(raw_dir, clean)
        except Exception as e:
            raise click.ClickException(str(e))
        click.echo(f"[agentkb] @{clean}: fetched {stats['fetched']}, kept {stats['kept']}")
        return

    stats = fetch(raw_dir)
    click.echo(
        f"[agentkb] X fetch: {stats['handles']} handles, "
        f"{stats['fetched']} fetched, {stats['kept']} kept"
    )
    if stats.get("errors"):
        for err in stats["errors"]:
            click.echo(f"  ! {err}", err=True)


# --- Cross-source: fetch, render, index ---


def _fetch_all_sources() -> dict:
    from agentkb.communications.sources import SOURCES
    raw_dir = _raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    totals = {"fetched": 0, "kept": 0}
    for src in SOURCES.values():
        try:
            stats = src.fetch(raw_dir / src.name)
        except Exception as e:
            click.echo(f"[agentkb] {src.name} fetch failed: {e}", err=True)
            continue
        totals["fetched"] += stats.get("fetched", 0)
        totals["kept"] += stats.get("kept", 0)
    return totals


def _render_all_sources() -> dict:
    from agentkb.communications.sources import SOURCES
    raw_dir = _raw_dir()
    readable_dir = _readable_dir()
    readable_dir.mkdir(parents=True, exist_ok=True)
    totals = {"generated": 0, "skipped": 0}
    for src in SOURCES.values():
        src_raw = raw_dir / src.name
        if not src_raw.exists():
            continue
        stats = src.render(src_raw, readable_dir)
        totals["generated"] += stats.get("generated", 0)
        totals["skipped"] += stats.get("skipped", 0)
    return totals


@communications.command("fetch")
def comms_fetch():
    """Fetch new data from every registered communication source."""
    stats = _fetch_all_sources()
    click.echo(f"[agentkb] Fetched {stats['fetched']} items, kept {stats['kept']}")


@communications.command("index")
@click.option("--model", help="Override ColBERT model name")
def comms_index(model):
    """Fetch, render, and index all communications."""
    from agentkb.communications.parser import build_communications_index

    click.echo("[agentkb] Fetching from communication sources...")
    fstats = _fetch_all_sources()
    if fstats["fetched"]:
        click.echo(f"  Fetched {fstats['fetched']} items, kept {fstats['kept']}")

    click.echo("[agentkb] Rendering readable markdown...")
    rstats = _render_all_sources()
    if rstats["generated"]:
        click.echo(f"  Generated {rstats['generated']} readable files ({rstats['skipped']} unchanged)")

    readable_dir = _readable_dir()
    if not readable_dir.exists():
        click.echo("[agentkb] No readable communications to index.")
        return

    stats = build_communications_index(readable_dir, _index_dir(), model_name=model)
    if not stats.get("up_to_date"):
        click.echo(
            f"[agentkb] Indexed {stats['chunks_indexed']} chunks from {stats['files_parsed']} files"
        )
    click.echo(f"[agentkb] Communications index at {_index_dir()}")


# --- List / show (mirrors chats) ---


def _first_heading(text: str) -> str:
    for line in strip_frontmatter(text).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _item_datetime(date_value: str, fallback_path: Path) -> datetime:
    if date_value:
        try:
            parsed = parse_time_filter(date_value)
            if parsed is not None:
                return parsed
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)


def _item_from_markdown(readable_dir: Path, md_file: Path) -> dict:
    text = md_file.read_text(errors="replace")
    fm = parse_frontmatter(text)
    body = strip_frontmatter(text)
    rel = md_file.relative_to(readable_dir).as_posix()

    title = str(fm.get("title") or _first_heading(body) or md_file.stem)
    return {
        "id": rel,
        "title": title,
        "source": str(fm.get("source") or ""),
        "handle": str(fm.get("handle") or ""),
        "kind": str(fm.get("kind") or ""),
        "date": str(fm.get("date") or ""),
        "url": str(fm.get("url") or ""),
        "length": fm.get("length") or 1,
        "path": str(md_file),
        "_item_time": _item_datetime(str(fm.get("date") or ""), md_file),
    }


@communications.command("list")
@click.option("--since", help="Only include items on or after this time filter")
@click.option("--until", help="Only include items on or before this time filter")
@click.option("--source", help="Filter by source, e.g. x")
@click.option("--handle", help="Filter by handle (for x)")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, None))
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
def comms_list(since, until, source, handle, limit, json_output):
    """List communications in the readable store."""
    try:
        since_dt = parse_time_filter(since) if since else None
        until_dt = parse_time_filter(until, end_of_day=True) if until else None
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    readable_dir = _readable_dir()
    items: list[dict] = []
    if readable_dir.exists():
        for md in sorted(readable_dir.rglob("*.md")):
            if md.name.startswith("_"):
                continue
            item = _item_from_markdown(readable_dir, md)
            if source and item["source"].lower() != source.lower():
                continue
            if handle and item["handle"].lower() != handle.lstrip("@").lower():
                continue
            t = item["_item_time"]
            if since_dt and t < since_dt:
                continue
            if until_dt and t > until_dt:
                continue
            items.append(item)

    items.sort(key=lambda i: (i["_item_time"], i["id"]), reverse=True)
    for i in items:
        i.pop("_item_time", None)
    items = items[:limit]

    if json_output:
        click.echo(json_mod.dumps({"items": items, "meta": {"count": len(items), "store": "communications"}}, indent=2))
        return

    if not items:
        click.echo("[agentkb] No communications found.")
        return

    for i in items:
        parts = [i["id"]]
        if i["date"]:
            parts.append(i["date"])
        if i["source"]:
            label = f"{i['source']}/@{i['handle']}" if i["handle"] else i["source"]
            parts.append(label)
        parts.append(i["title"])
        click.echo(" — ".join(parts))


@communications.command("show")
@click.option("--id", "item_id", required=True, help="Item id returned by `agentkb store communications list`")
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
def comms_show(item_id, json_output):
    """Read one communication from the readable store."""
    readable_dir = _readable_dir()
    root = readable_dir.resolve()
    candidate = (readable_dir / item_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise click.ClickException("id must resolve within the readable communications directory.") from exc
    if candidate.suffix != ".md" or not candidate.exists():
        raise click.ClickException(f"Communication not found: {item_id}")

    item = _item_from_markdown(readable_dir, candidate)
    item.pop("_item_time", None)
    item["content"] = candidate.read_text(errors="replace")

    if json_output:
        click.echo(json_mod.dumps({"item": item}, indent=2))
        return
    click.echo(item["content"])


@communications.command("status")
def comms_status():
    """Show communications store status."""
    from agentkb.store import IndexStore
    from agentkb.communications.sources.x import load_handles

    x_raw = _x_raw_dir()
    if x_raw.exists():
        handles = load_handles(x_raw)
        click.echo(f"[agentkb] X handles tracked: {len(handles)}")
    else:
        click.echo("[agentkb] X handles tracked: 0 (use `agentkb communications x add-handle`)")

    readable_dir = _readable_dir()
    if readable_dir.exists():
        md_count = sum(1 for f in readable_dir.rglob("*.md") if not f.name.startswith("_"))
        click.echo(f"[agentkb] Readable items: {md_count}")
        click.echo(f"  Browse: {readable_dir}/_index.md")

    index_dir = _index_dir()
    if index_dir.exists():
        store = IndexStore(index_dir)
        if store.exists():
            click.echo(
                f"[agentkb] Communications index: {store.document_count()} chunks "
                f"across {store.file_count()} files"
            )
            store.close()
    else:
        click.echo("[agentkb] Communications index: not built (run `agentkb store communications index`)")
