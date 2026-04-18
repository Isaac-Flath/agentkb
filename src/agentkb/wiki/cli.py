from __future__ import annotations

import json as json_mod
from datetime import datetime, timezone
from pathlib import Path

import click

from agentkb.config import paths
from agentkb.utils import parse_frontmatter, parse_time_filter


@click.group()
def wiki():
    """Wiki operations."""
    pass


def _wiki_pages_dir() -> Path:
    return paths.wiki_dir() / "wiki"


def _wiki_item_from_page(pages_dir: Path, md_file: Path) -> dict:
    text = md_file.read_text(errors="replace")
    frontmatter = parse_frontmatter(text)
    tags = frontmatter.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]

    mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)

    return {
        "path": md_file.relative_to(pages_dir).as_posix(),
        "title": str(frontmatter.get("title") or md_file.stem),
        "tags": [str(tag) for tag in tags],
        "mtime": mtime.isoformat().replace("+00:00", "Z"),
        "_item_time": mtime,
    }


@wiki.command("init")
@click.argument("path", required=False)
def wiki_init(path):
    """Initialize a wiki."""
    from agentkb.wiki.manager import KnowledgeBase

    if path:
        wiki_path = Path(path)
    else:
        wiki_path = paths.wiki_dir()

    KnowledgeBase.init(wiki_path)
    click.echo(f"[agentkb] Wiki initialized at {wiki_path}")
    click.echo()
    click.echo("  wiki/       -- pages go here")
    click.echo("  sources/    -- raw input documents")
    click.echo("  schema.md   -- conventions")
    click.echo("  index.md    -- content catalog")
    click.echo("  log.md      -- operation log")


@wiki.command("ingest")
@click.argument("source")
def wiki_ingest(source):
    """Add a source file to the wiki."""
    from agentkb.wiki.manager import KnowledgeBase

    wiki_path = paths.wiki_dir()
    kbase = KnowledgeBase(wiki_path)
    dest = kbase.ingest(source)
    click.echo(f"[agentkb] Ingested source to {dest}")


@wiki.command("index")
@click.option("--model", help="Override ColBERT model name")
def wiki_index(model):
    """Build or update wiki search index."""
    from agentkb.wiki.parser import build_wiki_index

    wiki_path = paths.wiki_dir()

    if not wiki_path.exists():
        click.echo("[agentkb] No wiki found. Run `agentkb store wiki init` first.")
        return

    wiki_index_dir = wiki_path / ".index"
    stats = build_wiki_index(wiki_path, wiki_index_dir, model_name=model)
    if stats.get("chunks_indexed", 0) > 0:
        click.echo(
            f"[agentkb] Indexed {stats['chunks_indexed']} wiki chunks "
            f"({stats.get('wiki_chunks', 0)} wiki, {stats.get('source_chunks', 0)} sources)"
        )
    elif stats.get("up_to_date"):
        click.echo("[agentkb] Wiki index is up to date.")


@wiki.command("list")
@click.option("--tag", help="Filter by tag")
@click.option("--since", help="Only include pages on or after this time filter")
@click.option("--until", help="Only include pages on or before this time filter")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, None))
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
def wiki_list(tag, since, until, limit, json_output):
    """List wiki pages with light metadata."""
    pages_dir = _wiki_pages_dir()

    try:
        since_dt = parse_time_filter(since) if since else None
        until_dt = parse_time_filter(until, end_of_day=True) if until else None
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    if not pages_dir.exists():
        payload = {
            "items": [],
            "meta": {"count": 0, "store": "wiki"},
            "message": "[agentkb] No wiki found. Run `agentkb store wiki init` first.",
        }
        if json_output:
            click.echo(json_mod.dumps(payload, indent=2))
        else:
            click.echo(payload["message"])
        return

    tag_filter = tag.lower() if tag else None
    items: list[dict] = []
    for md_file in sorted(pages_dir.rglob("*.md")):
        item = _wiki_item_from_page(pages_dir, md_file)

        if tag_filter and not any(existing.lower() == tag_filter for existing in item["tags"]):
            continue
        if since_dt is not None and item["_item_time"] < since_dt:
            continue
        if until_dt is not None and item["_item_time"] > until_dt:
            continue

        items.append(item)

    items.sort(key=lambda item: (item["_item_time"], item["path"]), reverse=True)
    for item in items:
        item.pop("_item_time", None)

    items = items[:limit]
    payload = {"items": items, "meta": {"count": len(items), "store": "wiki"}}

    if json_output:
        click.echo(json_mod.dumps(payload, indent=2))
        return

    if not items:
        click.echo("[agentkb] No wiki pages found.")
        return

    for item in items:
        parts = [item["path"], item["title"]]
        if item["tags"]:
            parts.append(f"tags: {', '.join(item['tags'])}")
        click.echo(" — ".join(parts))


@wiki.command("status")
def wiki_status():
    """Show wiki status."""
    from agentkb.wiki.manager import KnowledgeBase
    from agentkb.store import IndexStore

    wiki_path = paths.wiki_dir()

    if not wiki_path.exists():
        click.echo("[agentkb] No wiki found.")
        click.echo("  Run `agentkb store wiki init` to create one.")
        return

    kbase = KnowledgeBase(wiki_path)
    stats = kbase.status()

    click.echo(f"[agentkb] Wiki status")
    click.echo(f"  Path:        {wiki_path}")
    click.echo(f"  Wiki pages:  {stats['wiki_pages']}")
    click.echo(f"  Sources:     {stats['sources']}")

    wiki_index_dir = wiki_path / ".index"
    if wiki_index_dir.exists():
        store = IndexStore(wiki_index_dir)
        if store.exists():
            chunks = store.document_count()
            click.echo(f"  Index:       {chunks} chunks indexed")
            store.close()
