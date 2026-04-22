"""`agentkb refs ...` commands."""

from __future__ import annotations

import click

from agentkb import references
from agentkb.references.manifest import refs_root


def _format_status(status: str) -> str:
    """Shorten a sync status for CLI display, but keep error messages intact."""
    if not status or status.startswith("error"):
        return status or "unknown"
    if len(status) > 12:
        return status[:12]
    return status


@click.group()
def refs():
    """Manage external reference mirrors indexed into the wiki."""
    pass


@refs.command("add")
@click.argument("url")
@click.option("--id", "ref_id", help="Slug for the ref (default: inferred from URL)")
@click.option("--kind", type=click.Choice(["git", "url"]), help="Fetcher kind (default: inferred)")
@click.option("--subpath", help="For git refs, restrict to this subdirectory")
@click.option("--refresh", type=click.Choice(["pull", "never"]), help="Refresh policy")
@click.option("--sync/--no-sync", default=True, help="Fetch immediately after adding (default: true)")
def refs_add(url, ref_id, kind, subpath, refresh, sync):
    """Add a reference by URL and fetch it."""
    try:
        ref = references.add(url, ref_id=ref_id, kind=kind, subpath=subpath, refresh=refresh)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"[agentkb] Added {ref.id} ({ref.kind}) -> {ref.source}")
    if sync:
        results = references.sync(ref.id)
        status = results.get(ref.id, "unknown")
        click.echo(f"[agentkb] Fetched {ref.id}: {_format_status(status)}")
        click.echo(f"[agentkb] Content at: {refs_root() / ref.id}")
        click.echo("[agentkb] Run `agentkb index` to index the new content.")


@refs.command("list")
def refs_list():
    """List configured refs."""
    refs_data = references.list_refs()
    if not refs_data:
        click.echo("[agentkb] No refs configured. Add one with `agentkb refs add <url>`.")
        return
    for r in refs_data:
        extra = []
        if r.subpath:
            extra.append(f"subpath={r.subpath}")
        if r.last_commit:
            extra.append(f"@{r.last_commit[:8]}")
        if r.refresh != "pull":
            extra.append(f"refresh={r.refresh}")
        suffix = f"  ({', '.join(extra)})" if extra else ""
        click.echo(f"  {r.id}  [{r.kind}]  {r.source}{suffix}")


@refs.command("remove")
@click.argument("ref_id")
def refs_remove(ref_id):
    """Remove a ref and delete its local content."""
    if not references.remove(ref_id):
        raise click.ClickException(f"no ref with id {ref_id!r}")
    click.echo(f"[agentkb] Removed {ref_id}")


@refs.command("sync")
@click.argument("ref_id", required=False)
def refs_sync(ref_id):
    """Fetch (or refresh) one ref or all refs."""
    results = references.sync(ref_id)
    if "error" in results:
        raise click.ClickException(results["error"])
    if not results:
        click.echo("[agentkb] Nothing to sync.")
        return
    for rid, status in results.items():
        click.echo(f"  {rid}: {_format_status(status)}")
    click.echo()
    click.echo("[agentkb] Run `agentkb index` to pick up the changes.")
