"""CLI hub: registers store-specific command groups and cross-cutting commands."""

import json as json_mod
from pathlib import Path

import click

from agentkb.config import Settings, SETTINGS_DEFAULTS, paths
from agentkb.output import echo_status


class DefaultSearchGroup(click.Group):
    """Click group that treats unknown args as a search query."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["search", " ".join(args)]
        return super().parse_args(ctx, args)


@click.group(cls=DefaultSearchGroup)
def main():
    """Unified search and knowledge tool for AI agents and developers."""
    pass


# --- Refs: top-level command group ---

from agentkb.references.cli import refs  # noqa: E402

main.add_command(refs)


# --- Cross-cutting: search ---


from agentkb import chats as chats_store  # noqa: E402
from agentkb import communications as communications_store  # noqa: E402
from agentkb import skills as skills_store  # noqa: E402
from agentkb import wiki as wiki_store  # noqa: E402
from agentkb.chats.renderer import (  # noqa: E402
    export_all_sessions,
    export_readable,
    migrate_sessions_layout,
)
from agentkb.communications.sources import SOURCES as COMMUNICATIONS_SOURCES  # noqa: E402
from agentkb.encoder import DEFAULT_MODEL, get_encoder  # noqa: E402
from agentkb.prompts import resolve_prompt  # noqa: E402
from agentkb.search import (  # noqa: E402
    merge_multi_collection,
    merge_query_with_pattern,
    search as run_search,
)
from agentkb.sync import (  # noqa: E402
    pull as do_pull,
    push as do_push,
    status as get_sync_status,
)
from agentkb.traceability import SearchTrace, _db_path, pull_s3, push_s3  # noqa: E402


# Communications is intentionally NOT in `all` — privacy-sensitive data stays
# opt-in via an explicit `-s communications`.
SEARCH_STORES = {
    "wiki": wiki_store,
    "chats": chats_store,
    "communications": communications_store,
}
STATUS_STORES = [wiki_store, chats_store, communications_store, skills_store]


@main.command()
@click.argument("query")
@click.option("-s", "--scope", type=click.Choice(["wiki", "wiki:notes", "wiki:source", "chats", "communications", "all"]), default="wiki")
@click.option("-e", "pattern", help="Regex pre-filter")
@click.option("-F", "fixed", is_flag=True, help="Fixed string matching")
@click.option("-w", "word", is_flag=True, help="Word boundary matching")
@click.option("-l", "files_only", is_flag=True, help="Files/pages only")
@click.option("-c", "full_content", is_flag=True, help="Full content output")
@click.option("-k", "top_k", type=int, default=lambda: Settings().get("top_k"), help="Top-k results (default from settings)")
@click.option("-n", "context_lines", default=6, help="Context lines")
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
@click.option("--include", multiple=True, help="Include files matching glob")
@click.option("--exclude", multiple=True, help="Exclude files matching glob")
@click.option("--exclude-dir", multiple=True, help="Exclude directory")
@click.option("--semantic-only", is_flag=True, help="Skip keyword search")
def search(query, scope, pattern, fixed, word, files_only, full_content,
           top_k, context_lines, json_output, include, exclude, exclude_dir, semantic_only):
    """Search wiki, chats, or all."""
    scopes = ["wiki", "chats"] if scope == "all" else [scope]
    stores_to_search: list[tuple[str, object]] = []
    for name in scopes:
        # wiki:notes / wiki:source narrow the collection filter but still
        # live in the wiki store.
        store_key = "wiki" if name.startswith("wiki") else name
        module = SEARCH_STORES[store_key]
        store = module.ensure_search_store(json_output=json_output)
        if store is not None:
            stores_to_search.append((name, store))
        elif name == scope:
            echo_status(module.NOT_READY_MESSAGE, json_output=json_output)

    if not stores_to_search:
        message = "[agentkb] No indexes found. Run `agentkb index` to build them."
        echo_status(message, json_output=json_output)
        if json_output:
            click.echo(json_mod.dumps({"results": [], "message": message}, indent=2))
        return

    semantic_query = merge_query_with_pattern(query, pattern) if pattern and not fixed else query
    query_embedding = get_encoder().encode_query(semantic_query)
    all_exclude = tuple(exclude) + tuple(f"*/{d}/*" for d in exclude_dir)

    per_store_results = []
    for scope_label, store in stores_to_search:
        trace = SearchTrace(
            original_query=query, semantic_query=semantic_query, pattern=pattern,
            fixed=fixed, word=word, scope=scope, top_k=top_k, include=include,
            exclude=all_exclude, semantic_only=semantic_only, model_name=DEFAULT_MODEL,
            collection=scope_label,
        )
        results = run_search(
            store=store, query_embedding=query_embedding, query_text=query,
            scope=scope_label, top_k=top_k, pattern=pattern, fixed=fixed,
            word=word, include=include, exclude=all_exclude, semantic_only=semantic_only,
            trace=trace,
        )
        try:
            trace.save()
        except Exception:
            pass
        per_store_results.append(results)

    if len(per_store_results) > 1:
        all_results = merge_multi_collection(per_store_results, top_k=top_k)
    else:
        all_results = per_store_results[0] if per_store_results else []

    if json_output:
        click.echo(json_mod.dumps({"results": [r.to_json() for r in all_results]}, indent=2))
    elif files_only:
        seen = set()
        for r in all_results:
            key = f"[{r.collection}] {r.file}"
            if key not in seen:
                click.echo(key)
                seen.add(key)
    else:
        if not all_results:
            click.echo(f'[agentkb] No results for "{query}"')
        for r in all_results:
            if full_content:
                context_lines = 999
            click.echo(r.format_terminal(context_lines=context_lines))
            click.echo()


# --- Cross-cutting: index all ---


@main.command()
@click.option("--model", help="Override ColBERT model name")
@click.option("--no-fetch", is_flag=True, help="Skip all network calls (git pull/push, refs, communications)")
@click.option("--rebuild", is_flag=True, help="Drop every store's existing index and re-encode from scratch")
def index(model, no_fetch, rebuild):
    """Sync, fetch, render, and index everything.

    Default flow: ``sync pull`` → refs sync → reindex → ``sync push``, so
    local indexes reflect the latest remote state and your updates get
    published. Per-source failures are logged but don't abort the run.
    Use ``--no-fetch`` to skip every network call. Use ``--rebuild`` to
    force a full re-encode instead of the default incremental update.
    """
    if not no_fetch:
        _sync_pull_for_index()
        from agentkb import references as refs_store
        results = refs_store.sync()
        errors = [rid for rid, status in results.items() if isinstance(status, str) and status.startswith("error")]
        if errors:
            click.echo(f"[agentkb] refs: {len(errors)} failed ({', '.join(errors)})")

    for label, stats in [
        ("Wiki", wiki_store.reindex(model=model, rebuild=rebuild)),
        ("chat", chats_store.reindex(model=model, rebuild=rebuild)),
        ("communication", communications_store.reindex(model=model, fetch=not no_fetch, rebuild=rebuild)),
    ]:
        if stats.get("chunks_indexed", 0) > 0 and not stats.get("up_to_date"):
            click.echo(f"[agentkb] Indexed {stats['chunks_indexed']} {label} chunks")

    if not no_fetch:
        _sync_push_for_index()


def _sync_pull_for_index() -> None:
    """Pull configured git stores + traceability DB. Silent skip if unconfigured."""
    try:
        results = do_pull()
    except RuntimeError:
        results = {}
    for name, st in results.items():
        if isinstance(st, str) and st.startswith("error"):
            click.echo(f"[agentkb] pull {name}: {st}")
    try:
        tb = pull_s3()
        if tb.startswith("error") or tb.startswith("skipped"):
            return
    except RuntimeError:
        pass  # S3 not configured.
    except Exception as e:
        click.echo(f"[agentkb] pull traceability: error: {e}")


def _sync_push_for_index() -> None:
    """Push configured git stores + traceability DB. Silent skip if unconfigured."""
    try:
        results = do_push()
    except RuntimeError:
        results = {}
    for name, st in results.items():
        if st == "up to date":
            continue
        click.echo(f"[agentkb] push {name}: {st}")
    try:
        tb = push_s3()
    except RuntimeError:
        return  # S3 not configured.
    except Exception as e:
        click.echo(f"[agentkb] push traceability: error: {e}")
        return
    if tb != "ok":
        click.echo(f"[agentkb] push traceability: {tb}")


# --- Cross-cutting: status ---


@main.command()
def status():
    """Show status of all collections."""
    click.echo("[agentkb] Status")
    click.echo()
    for module in STATUS_STORES:
        for line in module.status_lines():
            click.echo(line)


# --- Settings, sync ---


def _settings_payload() -> dict:
    """Machine-readable settings payload for agents and other tools."""
    s = Settings()
    wiki_root = paths.wiki_dir()
    chats_root = paths.chats_dir()
    communications_root = paths.communications_dir()
    references_root = paths.references_dir()
    skills_root = paths.skills_dir()

    return {
        "config_file": str(paths.config_file()),
        "settings": s.all(),
        "resolved_paths": {
            "agentkb_home": str(paths.agentkb_home()),
            "wiki_root": str(wiki_root),
            "wiki_pages": str(wiki_root / "wiki"),
            "wiki_sources": str(wiki_root / "sources"),
            "chats_root": str(chats_root),
            "chats_sessions": str(paths.chats_sessions_dir()),
            "chats_readable": str(paths.chats_readable_dir()),
            "communications_root": str(communications_root),
            "references_root": str(references_root),
            "skills_root": str(skills_root),
        },
    }


@main.group(invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
@click.pass_context
def settings(ctx, json_output):
    """View or update agentkb configuration."""
    if ctx.invoked_subcommand is None:
        payload = _settings_payload()
        if json_output:
            click.echo(json_mod.dumps(payload, indent=2))
            return

        path_resolvers = {
            "wiki_path": "wiki_root",
            "chats_path": "chats_root",
            "communications_path": "communications_root",
            "references_path": "references_root",
            "skills_path": "skills_root",
        }
        click.echo(f"[agentkb] Config file: {payload['config_file']}")
        click.echo()
        for key, value in payload["settings"].items():
            default = SETTINGS_DEFAULTS.get(key)
            if value == default and key in path_resolvers:
                resolved = payload["resolved_paths"][path_resolvers[key]]
                click.echo(f"  {key}: {resolved} (default)")
            elif value == default:
                click.echo(f"  {key}: {value}")
            else:
                click.echo(f"  {key}: {value} (custom)")


@settings.command("set")
@click.argument("key")
@click.argument("value")
def settings_set(key, value):
    """Set a configuration value."""
    if key not in SETTINGS_DEFAULTS:
        click.echo(f"[agentkb] Unknown setting: {key}")
        click.echo(f"  Valid settings: {', '.join(SETTINGS_DEFAULTS.keys())}")
        return
    s = Settings()
    s.set(key, value)
    click.echo(f"[agentkb] Set {key} = {s.get(key)}")


@main.group()
def sync():
    """Sync agentkb data to/from git remotes."""
    pass


@sync.command()
@click.option("--dry-run", is_flag=True, help="Show what would be synced without doing it")
@click.option("-v", "verbose", is_flag=True, help="Verbose output")
def push(dry_run, verbose):
    """Commit and push local changes to git remotes and S3."""
    try:
        results = do_push(dry_run=dry_run, verbose=verbose)
    except RuntimeError as e:
        click.echo(f"[agentkb] {e}")
        return

    # Traceability DB -> S3
    if not dry_run:
        try:
            results["traceability"] = push_s3(verbose=verbose)
        except Exception as e:
            results["traceability"] = f"error: {e}"

    click.echo("[agentkb] Sync push results:")
    for name, st in results.items():
        click.echo(f"  {name}: {st}")


@sync.command()
@click.option("--dry-run", is_flag=True, help="Show what would be synced without doing it")
@click.option("-v", "verbose", is_flag=True, help="Verbose output")
def pull(dry_run, verbose):
    """Pull latest changes from git remotes and S3."""
    try:
        results = do_pull(dry_run=dry_run, verbose=verbose)
    except RuntimeError as e:
        click.echo(f"[agentkb] {e}")
        return

    # Traceability DB <- S3
    if not dry_run:
        try:
            results["traceability"] = pull_s3(verbose=verbose)
        except Exception as e:
            results["traceability"] = f"error: {e}"

    click.echo("[agentkb] Sync pull results:")
    for name, st in results.items():
        click.echo(f"  {name}: {st}")
    if not dry_run:
        click.echo()
        click.echo("Indexes rebuild automatically on next search.")


@sync.command("status")
def sync_status():
    """Show sync configuration."""
    info = get_sync_status()

    for name, store in info.items():
        click.echo(f"[agentkb] {name}:")
        if not store.get("remote"):
            click.echo(f"  Not configured. Set with: agentkb settings set {name}_remote \"git@github.com:user/{name}.git\"")
        else:
            click.echo(f"  Remote: {store['remote']}")
            click.echo(f"  Local:  {store.get('local', 'default')}")
            if store.get("exists"):
                click.echo(f"  Status: {'git repo' if store.get('is_repo') else 'exists (not a git repo)'}")
            else:
                click.echo(f"  Status: not cloned (run `agentkb sync pull` to clone)")
        click.echo()

    # Traceability S3 status
    s = Settings()
    bucket = s.get("traceability_s3_bucket")
    key = s.get("traceability_s3_key")
    db = _db_path()
    click.echo("[agentkb] traceability:")
    if bucket:
        click.echo(f"  S3: s3://{bucket}/{key}")
    else:
        click.echo('  S3: not configured (set traceability_s3_bucket)')
    if db.exists():
        size_mb = db.stat().st_size / (1024 * 1024)
        click.echo(f"  Local: {db} ({size_mb:.1f} MB)")
    else:
        click.echo(f"  Local: not created yet")
    click.echo()



def _emit_consolidate_chats(since: str) -> None:
    wiki_path = paths.wiki_dir()
    readable_dir = paths.chats_readable_dir()
    sessions_dir = paths.chats_sessions_dir()

    migrate_sessions_layout(sessions_dir)
    export_all_sessions(sessions_dir)
    if sessions_dir.exists():
        export_readable(sessions_dir, readable_dir)

    path_lines = []
    if wiki_path.exists():
        path_lines.append(f"- Wiki: {wiki_path}")
        path_lines.append(f"- Schema: {wiki_path}/schema.md")
        path_lines.append(f"- Index: {wiki_path}/index.md")
        path_lines.append(f"- Pages: {wiki_path}/wiki/")
    if readable_dir.exists():
        path_lines.append(f"- Readable chat exports: {readable_dir}")
    if sessions_dir.exists():
        path_lines.append(f"- Raw JSONL sessions: {sessions_dir}")
    chats_remote = Settings().get("chats_remote") or ""
    if chats_remote:
        browse_url = chats_remote.replace(".git", "").replace("git@github.com:", "https://github.com/")
        path_lines.append(f"- Chat history repo: {browse_url}")

    template = resolve_prompt("consolidate_chats")
    click.echo(template.format(paths="\n".join(path_lines), since=since))


def _emit_consolidate_communications(since: str) -> None:
    """Emit the consolidate-communications prompt.

    Re-renders readable markdown from existing raw data (no API fetch) so the
    report paths point at current files, but never spends X credits here —
    that's what `agentkb index` is for.
    """
    comms_root = paths.communications_dir()
    raw_dir = comms_root / "raw"
    readable_dir = comms_root / "readable"

    if raw_dir.exists():
        for src in COMMUNICATIONS_SOURCES.values():
            src_raw = raw_dir / src.name
            if src_raw.exists():
                try:
                    src.render(src_raw, readable_dir)
                except Exception:
                    pass

    wiki_path = paths.wiki_dir()
    path_lines = []
    if wiki_path.exists():
        path_lines.append(f"- Wiki: {wiki_path}")
        path_lines.append(f"- Schema: {wiki_path}/schema.md")
        path_lines.append(f"- Index: {wiki_path}/index.md")
        path_lines.append(f"- Pages: {wiki_path}/wiki/")
    if readable_dir.exists():
        path_lines.append(f"- Readable threads: {readable_dir}")
        path_lines.append(f"- Thread index: {readable_dir}/_index.md")
    if raw_dir.exists():
        path_lines.append(f"- Raw JSONL: {raw_dir}")
    handles_path = raw_dir / "x" / "_handles.json"
    if handles_path.exists():
        path_lines.append(f"- X handles manifest: {handles_path}")
    comms_remote = Settings().get("communications_remote") or ""
    if comms_remote:
        browse_url = comms_remote.replace(".git", "").replace("git@github.com:", "https://github.com/")
        path_lines.append(f"- Communications repo: {browse_url}")

    template = resolve_prompt("consolidate_communications")
    click.echo(template.format(paths="\n".join(path_lines), since=since))


@main.group(invoke_without_command=True)
@click.option("--since", default="7 days", help="Time range in natural language (default: '7 days')")
@click.pass_context
def consolidate(ctx, since):
    """Produce a consolidation prompt for the wiki.

    Without a subcommand, defaults to `chats` for backward compatibility.
    Use `chats` or `communications` explicitly to pick the source store.
    """
    if ctx.invoked_subcommand is None:
        _emit_consolidate_chats(since)


@consolidate.command("chats")
@click.option("--since", default="7 days", help="Time range (default: '7 days')")
def consolidate_chats_cmd(since):
    """Consolidate chat sessions into the wiki."""
    _emit_consolidate_chats(since)


@consolidate.command("communications")
@click.option("--since", default="7 days", help="Time range (default: '7 days')")
def consolidate_communications_cmd(since):
    """Consolidate X/communication threads into the wiki.

    Focuses on retrieval approaches, paper links, and results from tracked
    handles. Does NOT fetch from the X API — re-renders existing raw data
    so the report points at current readable files.
    """
    _emit_consolidate_communications(since)



