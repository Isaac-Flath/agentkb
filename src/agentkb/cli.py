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


# --- Store namespace ---
# Store-specific operations live under `agentkb store <name> ...` so the top
# level stays focused on cross-cutting commands (search, index, status, sync,
# settings, consolidate).

from agentkb.wiki.cli import wiki  # noqa: E402
from agentkb.chats.cli import chats  # noqa: E402
from agentkb.communications.cli import communications  # noqa: E402
from agentkb.skills.cli import skills  # noqa: E402


@main.group()
def store():
    """Per-store operations: wiki, chats, communications, skills."""
    pass


store.add_command(wiki)
store.add_command(chats)
store.add_command(communications)
store.add_command(skills)


# --- Cross-cutting: search ---


def _search_status(message, *, json_output=False):
    """Emit search status without corrupting machine-readable JSON output."""
    echo_status(message, json_output=json_output)


def _ensure_wiki_store(scope, *, json_output=False):
    """Ensure wiki index is up to date. Returns (label, IndexStore) or None."""
    from agentkb.store import IndexStore
    from agentkb.wiki.parser import build_wiki_index, wiki_index_is_stale

    wiki_path = paths.wiki_dir()
    if not wiki_path.exists():
        if scope == "wiki":
            _search_status("[agentkb] No wiki found. Run `agentkb wiki init` first.", json_output=json_output)
        return None

    wiki_index = wiki_path / ".index"
    if not wiki_index.exists() or wiki_index_is_stale(wiki_path, wiki_index):
        _search_status("[agentkb] Updating Wiki index...", json_output=json_output)
        build_wiki_index(wiki_path, wiki_index, json_output=json_output)
    return ("wiki", IndexStore(wiki_index))


def _ensure_communications_store(scope, *, json_output=False):
    """Ensure communications index is up to date. Returns (label, IndexStore) or None.

    Does NOT auto-fetch from external APIs — only (re)renders existing raw data
    and rebuilds the index from changed readable files. Users fetch explicitly
    via `agentkb store communications fetch` or `agentkb store communications index`.
    """
    from agentkb.store import IndexStore
    from agentkb.communications.parser import (
        build_communications_index,
        communications_index_is_stale,
    )

    comms_dir = paths.communications_dir()
    readable_dir = comms_dir / "readable"
    index_dir = comms_dir / ".index"

    # Re-render from raw without fetching (cheap, no API calls).
    raw_dir = comms_dir / "raw"
    if raw_dir.exists():
        from agentkb.communications.sources import SOURCES
        for src in SOURCES.values():
            src_raw = raw_dir / src.name
            if src_raw.exists():
                try:
                    src.render(src_raw, readable_dir)
                except Exception:
                    pass

    if not readable_dir.exists():
        if scope == "communications":
            _search_status(
                "[agentkb] No communications found. Run `agentkb store communications index` first.",
                json_output=json_output,
            )
        return None

    if not index_dir.exists():
        _search_status("[agentkb] Building communications index...", json_output=json_output)
        build_communications_index(readable_dir, index_dir, json_output=json_output)
    elif communications_index_is_stale(readable_dir, index_dir):
        build_communications_index(readable_dir, index_dir, tracked_only=True, json_output=json_output)

    if index_dir.exists():
        return ("communications", IndexStore(index_dir))
    return None


def _ensure_chats_store(scope, *, json_output=False):
    """Ensure chats index is up to date. Returns (label, IndexStore) or None."""
    from agentkb.store import IndexStore
    from agentkb.chats.parser import export_all_sessions, migrate_sessions_layout, export_readable, build_chat_index, chat_index_is_stale

    chats_index_dir = paths.chats_dir() / ".index"
    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()

    migrate_sessions_layout(sessions_dir)
    export_all_sessions(sessions_dir)
    if sessions_dir.exists():
        export_readable(sessions_dir, readable_dir)

    if not readable_dir.exists():
        if scope == "chats":
            _search_status("[agentkb] No chat history found. Run `agentkb store chats index` first.", json_output=json_output)
        return None

    if not chats_index_dir.exists():
        _search_status("[agentkb] Building chat index...", json_output=json_output)
        build_chat_index(readable_dir, chats_index_dir, json_output=json_output)
    elif chat_index_is_stale(readable_dir, chats_index_dir):
        build_chat_index(readable_dir, chats_index_dir, tracked_only=True, json_output=json_output)
    if chats_index_dir.exists():
        return ("chats", IndexStore(chats_index_dir))
    return None


@main.command()
@click.argument("query")
@click.option("-s", "--scope", type=click.Choice(["wiki", "chats", "communications", "all"]), default="wiki")
@click.option("-e", "pattern", help="Regex pre-filter")
@click.option("-F", "fixed", is_flag=True, help="Fixed string matching")
@click.option("-w", "word", is_flag=True, help="Word boundary matching")
@click.option("-l", "files_only", is_flag=True, help="Files/pages only")
@click.option("-c", "full_content", is_flag=True, help="Full content output")
@click.option("-k", "top_k", default=15, help="Top-k results")
@click.option("-n", "context_lines", default=6, help="Context lines")
@click.option("--json", "json_output", is_flag=True, help="JSON output for agents")
@click.option("--include", multiple=True, help="Include files matching glob")
@click.option("--exclude", multiple=True, help="Exclude files matching glob")
@click.option("--exclude-dir", multiple=True, help="Exclude directory")
@click.option("--semantic-only", is_flag=True, help="Skip keyword search")
def search(query, scope, pattern, fixed, word, files_only, full_content,
           top_k, context_lines, json_output, include, exclude, exclude_dir, semantic_only):
    """Search wiki, chats, or all."""
    from agentkb.search import merge_multi_collection, search as run_search

    # Build stores for requested scope.
    # Communications is intentionally NOT in `all` — privacy-sensitive data
    # stays opt-in via explicit `-s communications`.
    store_fns = {
        "wiki": _ensure_wiki_store,
        "chats": _ensure_chats_store,
        "communications": _ensure_communications_store,
    }
    scopes = ["wiki", "chats"] if scope == "all" else [scope]
    stores_to_search = [
        s for name in scopes if (s := store_fns[name](scope, json_output=json_output)) is not None
    ]

    if not stores_to_search:
        message = "[agentkb] No indexes found. Run `agentkb store wiki init` or `agentkb store chats index`."
        _search_status(message, json_output=json_output)
        if json_output:
            click.echo(json_mod.dumps({"results": [], "message": message}, indent=2))
        return

    from agentkb.encoder import get_encoder, DEFAULT_MODEL
    from agentkb.search import merge_query_with_pattern
    from agentkb.traceability import SearchTrace

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
@click.option("--no-fetch", is_flag=True, help="Skip fetching new communications from external sources")
def index(model, no_fetch):
    """Fetch, render, and index everything (wiki + chats + communications).

    Communications fetches hit external APIs (X); per-source failures are
    logged but don't abort the run. Use `--no-fetch` to skip network calls,
    or the per-store commands for granular control.
    """
    # Wiki index (if exists)
    wiki_path = paths.wiki_dir()
    if wiki_path.exists() and (wiki_path / "wiki").exists():
        from agentkb.wiki.parser import build_wiki_index
        wiki_stats = build_wiki_index(wiki_path, wiki_path / ".index", model_name=model)
        if wiki_stats["chunks_indexed"] > 0:
            click.echo(f"[agentkb] Indexed {wiki_stats['chunks_indexed']} Wiki chunks")

    # Chat index (if sessions exist)
    from agentkb.chats.parser import export_all_sessions, migrate_sessions_layout, export_readable, build_chat_index
    sessions_dir = paths.chats_sessions_dir()
    readable_dir = paths.chats_readable_dir()

    migrate_sessions_layout(sessions_dir)
    export_all_sessions(sessions_dir)
    if sessions_dir.exists():
        export_readable(sessions_dir, readable_dir)
    if readable_dir.exists():
        chat_stats = build_chat_index(readable_dir, paths.chats_dir() / ".index", model_name=model)
        if not chat_stats.get("up_to_date") and chat_stats.get("chunks_indexed", 0) > 0:
            click.echo(f"[agentkb] Indexed {chat_stats['chunks_indexed']} chat chunks")

    # Communications: fetch (unless --no-fetch), render, index
    from agentkb.communications.sources import SOURCES
    comms_dir = paths.communications_dir()
    comms_raw = comms_dir / "raw"
    comms_readable = comms_dir / "readable"

    if not no_fetch:
        comms_raw.mkdir(parents=True, exist_ok=True)
        for src in SOURCES.values():
            src_raw = comms_raw / src.name
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

    if comms_raw.exists():
        for src in SOURCES.values():
            src_raw = comms_raw / src.name
            if src_raw.exists():
                try:
                    src.render(src_raw, comms_readable)
                except Exception as e:
                    click.echo(f"[agentkb] {src.name} render failed: {e}", err=True)
    if comms_readable.exists():
        from agentkb.communications.parser import build_communications_index
        comms_stats = build_communications_index(comms_readable, comms_dir / ".index", model_name=model)
        if not comms_stats.get("up_to_date") and comms_stats.get("chunks_indexed", 0) > 0:
            click.echo(f"[agentkb] Indexed {comms_stats['chunks_indexed']} communication chunks")


# --- Cross-cutting: status ---


@main.command()
def status():
    """Show status of all collections."""
    from agentkb.store import IndexStore

    click.echo("[agentkb] Status")
    click.echo()

    # Wiki
    wiki_path = paths.wiki_dir()
    if wiki_path.exists():
        from agentkb.wiki.manager import KnowledgeBase
        stats = KnowledgeBase(wiki_path).status()
        click.echo(f"  Wiki: {stats['wiki_pages']} pages, {stats['sources']} sources")
        wiki_index = wiki_path / ".index"
        if wiki_index.exists():
            store = IndexStore(wiki_index)
            if store.exists():
                click.echo(f"  Wiki index: {store.document_count()} chunks indexed")
                store.close()
    else:
        click.echo("  Wiki: not initialized (run `agentkb store wiki init`)")

    # Chats
    chats_index = paths.chats_dir() / ".index"
    if chats_index.exists():
        store = IndexStore(chats_index)
        if store.exists():
            click.echo(f"  Chat history: {store.document_count()} chunks across {store.file_count()} session files")
            store.close()
    else:
        click.echo("  Chat history: not indexed (run `agentkb store chats index`)")

    # Communications
    comms_index = paths.communications_dir() / ".index"
    comms_raw = paths.communications_dir() / "raw"
    handle_count = 0
    if (comms_raw / "x" / "_handles.json").exists():
        from agentkb.communications.sources.x import load_handles
        handle_count = len(load_handles(comms_raw / "x"))
    if comms_index.exists():
        store = IndexStore(comms_index)
        if store.exists():
            click.echo(
                f"  Communications: {store.document_count()} chunks across {store.file_count()} files"
                + (f" ({handle_count} X handles)" if handle_count else "")
            )
            store.close()
    else:
        if handle_count:
            click.echo(f"  Communications: {handle_count} X handles tracked, not indexed (run `agentkb store communications index`)")
        else:
            click.echo("  Communications: not configured (run `agentkb store communications x add-handle <handle>`)")

    # Skills
    skills_dir = paths.skills_dir()
    if skills_dir.exists():
        from agentkb.skills.cli import _find_skills
        skill_files = _find_skills(skills_dir)
        click.echo(f"  Skills: {len(skill_files)} installed ({skills_dir})")
    else:
        s = Settings()
        if s.get("skills_remote"):
            click.echo("  Skills: not cloned (run `agentkb sync pull`)")
        else:
            click.echo("  Skills: not configured (set skills_remote)")


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

        click.echo(f"[agentkb] Config file: {payload['config_file']}")
        click.echo()
        for key, value in payload["settings"].items():
            default = SETTINGS_DEFAULTS.get(key)
            marker = "" if value == default else " (custom)"
            click.echo(f"  {key}: {value}{marker}")


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
    from agentkb.sync import push as do_push
    try:
        results = do_push(dry_run=dry_run, verbose=verbose)
    except RuntimeError as e:
        click.echo(f"[agentkb] {e}")
        return

    # Traceability DB -> S3
    if not dry_run:
        from agentkb.traceability import push_s3
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
    from agentkb.sync import pull as do_pull
    try:
        results = do_pull(dry_run=dry_run, verbose=verbose)
    except RuntimeError as e:
        click.echo(f"[agentkb] {e}")
        return

    # Traceability DB <- S3
    if not dry_run:
        from agentkb.traceability import pull_s3
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
    from agentkb.sync import status as get_status
    info = get_status()

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
    from agentkb.traceability import _db_path
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
    from agentkb.prompts import resolve_prompt
    from agentkb.chats.parser import export_all_sessions, migrate_sessions_layout, export_readable

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
    that's what `agentkb communications index` is for.
    """
    from agentkb.prompts import resolve_prompt
    from agentkb.communications.sources import SOURCES

    comms_root = paths.communications_dir()
    raw_dir = comms_root / "raw"
    readable_dir = comms_root / "readable"

    if raw_dir.exists():
        for src in SOURCES.values():
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



