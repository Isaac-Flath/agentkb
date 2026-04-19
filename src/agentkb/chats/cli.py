from __future__ import annotations

import json as json_mod
from datetime import datetime, timezone
from pathlib import Path

import click

from agentkb.config import paths
from agentkb.utils import parse_frontmatter, parse_time_filter, strip_frontmatter


@click.group()
def chats():
    """Chat history operations."""
    pass


def _ensure_readable_exports(project_filter: str | None = None) -> Path:
    """Refresh agentkb-owned session copies and readable markdown exports."""
    from agentkb.chats.renderer import export_all_sessions, export_readable, migrate_sessions_layout

    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()

    migrate_sessions_layout(sessions_dir)
    export_all_sessions(sessions_dir, project_filter=project_filter)
    if sessions_dir.exists():
        export_readable(sessions_dir, readable_dir, project_filter=project_filter)

    return readable_dir


def _first_heading(text: str) -> str:
    for line in strip_frontmatter(text).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _item_datetime(date_value: str, fallback_path: Path) -> datetime:
    if date_value:
        try:
            parsed = parse_time_filter(date_value)
            if parsed is not None:
                return parsed
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)


def _matches_time_range(
    item_time: datetime,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if since is not None and item_time < since:
        return False
    if until is not None and item_time > until:
        return False
    return True


def _chat_item_from_markdown(readable_dir: Path, md_file: Path) -> dict:
    text = md_file.read_text(errors="replace")
    frontmatter = parse_frontmatter(text)
    body = strip_frontmatter(text)
    rel_path = md_file.relative_to(readable_dir).as_posix()

    title = str(frontmatter.get("title") or _first_heading(body) or md_file.stem)
    project = str(frontmatter.get("project") or "")
    source = str(frontmatter.get("source") or "")
    session_id = str(frontmatter.get("session_id") or md_file.stem)
    date = str(frontmatter.get("date") or "")
    source_jsonl = str(frontmatter.get("source_jsonl") or "")
    messages = _as_int(frontmatter.get("messages"), default=0)
    item_time = _item_datetime(date, md_file)

    return {
        "id": rel_path,
        "title": title,
        "date": date,
        "source": source,
        "project": project,
        "session_id": session_id,
        "messages": messages,
        "path": str(md_file),
        "source_jsonl": source_jsonl,
        "_item_time": item_time,
    }


def _list_chat_items(
    readable_dir: Path,
    *,
    since: str | None = None,
    until: str | None = None,
    source: str | None = None,
    project: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    since_dt = parse_time_filter(since) if since else None
    until_dt = parse_time_filter(until, end_of_day=True) if until else None
    source_filter = source.lower() if source else None

    items: list[dict] = []
    for md_file in sorted(readable_dir.rglob("*.md")) if readable_dir.exists() else []:
        if md_file.name.startswith("_"):
            continue

        item = _chat_item_from_markdown(readable_dir, md_file)

        if source_filter and item["source"].lower() != source_filter:
            continue
        if project and project not in item["project"]:
            continue
        if not _matches_time_range(item["_item_time"], since_dt, until_dt):
            continue

        items.append(item)

    items.sort(key=lambda item: (item["_item_time"], item["id"]), reverse=True)

    for item in items:
        item.pop("_item_time", None)

    if limit is not None:
        return items[:limit]
    return items


def _resolve_chat_path(item_id: str) -> Path:
    readable_dir = _ensure_readable_exports()
    root = readable_dir.resolve()
    candidate = (readable_dir / item_id).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise click.ClickException("Chat id must resolve within the readable chats directory.") from exc

    if candidate.suffix != ".md" or not candidate.exists():
        raise click.ClickException(f"Chat session not found: {item_id}")

    return candidate


@chats.command("export")
@click.option("--project", help="Filter to sessions matching this project name substring")
def chats_export(project):
    """Export chat history from all sources to agentkb-owned storage.

    Copies JSONL from each registered source (Claude Code, Pi, etc.) into
    sessions/{source}/, then generates readable markdown in readable/.
    """
    from agentkb.chats.renderer import export_all_sessions, migrate_sessions_layout, export_readable

    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()

    migrate_sessions_layout(sessions_dir)

    # Step 1: Copy JSONL from all sources
    click.echo("[agentkb] Copying JSONL sessions...")
    jsonl_stats = export_all_sessions(sessions_dir, project_filter=project)
    if jsonl_stats["total"] == 0:
        click.echo("[agentkb] No chat history found from any source.")
        return
    click.echo(
        f"  {jsonl_stats['copied']} new/changed, "
        f"{jsonl_stats['skipped']} unchanged, "
        f"{jsonl_stats['total']} total"
    )

    # Step 2: Generate readable markdown
    click.echo("[agentkb] Generating readable markdown...")
    md_stats = export_readable(sessions_dir, readable_dir, project_filter=project)
    click.echo(
        f"  {md_stats['generated']} generated, "
        f"{md_stats['skipped']} unchanged"
    )
    click.echo(f"[agentkb] Readable sessions at {readable_dir}")


@chats.command("index")
@click.option("--model", help="Override ColBERT model name")
@click.option("--project", help="Filter to sessions matching this project name substring")
def chats_index(model, project):
    """Export and index chat history.

    Runs full pipeline: copy JSONL -> generate readable markdown -> build search index.
    The search index is built from the readable markdown, not raw JSONL.
    """
    from agentkb.chats.renderer import export_all_sessions, migrate_sessions_layout, export_readable
    from agentkb.chats.parser import build_chat_index

    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()

    migrate_sessions_layout(sessions_dir)

    # Step 1: Copy JSONL from all sources
    click.echo("[agentkb] Exporting new conversations...")
    jsonl_stats = export_all_sessions(sessions_dir, project_filter=project)
    if jsonl_stats["copied"] > 0:
        click.echo(f"  Exported {jsonl_stats['copied']} new/changed sessions")

    if not sessions_dir.exists():
        click.echo("[agentkb] No chat sessions found.")
        return

    # Step 2: Generate readable markdown
    click.echo("[agentkb] Generating readable markdown...")
    md_stats = export_readable(sessions_dir, readable_dir, project_filter=project)
    if md_stats["generated"] > 0:
        click.echo(f"  Generated {md_stats['generated']} readable files")

    # Step 3: Build search index from readable markdown
    if not readable_dir.exists():
        click.echo("[agentkb] No readable sessions to index.")
        return

    index_dir = paths.chats_dir() / ".index"
    stats = build_chat_index(
        projects_dir=readable_dir,
        index_dir=index_dir,
        model_name=model,
        project_filter=project,
    )

    if not stats.get("up_to_date"):
        click.echo(
            f"[agentkb] Indexed {stats['chunks_indexed']} chat chunks "
            f"from {stats['sessions_parsed']} sessions"
        )
    click.echo(f"[agentkb] Chat index saved to {index_dir}")


@chats.command("list")
@click.option("--since", help="Only include sessions on or after this time filter")
@click.option("--until", help="Only include sessions on or before this time filter")
@click.option("--source", help="Filter by chat source, e.g. pi or claude")
@click.option("--project", help="Filter by project substring")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, None))
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
def chats_list(since, until, source, project, limit, json_output):
    """List chat sessions from the readable chats store."""
    try:
        readable_dir = _ensure_readable_exports(project_filter=project)
        items = _list_chat_items(
            readable_dir,
            since=since,
            until=until,
            source=source,
            project=project,
            limit=limit,
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    payload = {"items": items, "meta": {"count": len(items), "store": "chats"}}

    if json_output:
        click.echo(json_mod.dumps(payload, indent=2))
        return

    if not items:
        click.echo("[agentkb] No chat sessions found.")
        return

    for item in items:
        source_project = f"{item['source']}/{item['project']}".rstrip("/")
        parts = [item["id"]]
        if item["date"]:
            parts.append(item["date"])
        if source_project:
            parts.append(source_project)
        parts.append(item["title"])
        click.echo(" — ".join(parts))


@chats.command("show")
@click.option("--id", "item_id", required=True, help="Chat id returned by `agentkb store chats list`")
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
def chats_show(item_id, json_output):
    """Read one chat session from the readable chats store."""
    md_file = _resolve_chat_path(item_id)
    readable_dir = paths.chats_readable_dir()
    item = _chat_item_from_markdown(readable_dir, md_file)
    item.pop("_item_time", None)
    item["content"] = md_file.read_text(errors="replace")

    if json_output:
        click.echo(json_mod.dumps({"item": item}, indent=2))
        return

    click.echo(item["content"])


@chats.command("status")
def chats_status():
    """Show chat history status."""
    from agentkb.store import IndexStore

    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()
    index_dir = paths.chats_dir() / ".index"

    if sessions_dir.exists():
        total = sum(1 for d in sessions_dir.iterdir() if d.is_dir()
                    for f in d.glob("*.jsonl"))
        click.echo(f"[agentkb] JSONL sessions: {total} files")

    if readable_dir.exists():
        md_count = sum(1 for f in readable_dir.rglob("*.md") if f.name != "_index.md")
        click.echo(f"[agentkb] Readable exports: {md_count} markdown files")
        click.echo(f"  Browse: {readable_dir}/_index.md")

    if index_dir.exists():
        store = IndexStore(index_dir)
        if store.exists():
            chunks = store.document_count()
            sessions = store.file_count()
            click.echo(f"[agentkb] Search index: {chunks} chunks across {sessions} files")
            store.close()
    else:
        click.echo("[agentkb] Search index: not built (run `agentkb store chats index`)")
