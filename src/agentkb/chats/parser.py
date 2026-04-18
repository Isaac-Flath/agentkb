"""Chat history parsing, export, and indexing for Claude Code JSONL conversations."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from agentkb.utils import file_hash
from agentkb.encoder import get_encoder
from agentkb.output import echo_status
from agentkb.store import IndexStore



def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Create a searchable summary of tool input."""
    if not isinstance(tool_input, dict):
        return ""

    _TOOL_FIELDS = {
        "Bash": "command", "bash": "command",
        "Read": "file_path", "read": "file_path",
        "Write": "file_path", "write": "file_path",
        "Edit": "file_path", "edit": "file_path",
    }

    if tool_name in _TOOL_FIELDS:
        return tool_input.get(_TOOL_FIELDS[tool_name], "")
    if tool_name in ("Grep", "grep", "Glob", "glob"):
        return f'{tool_input.get("pattern", "")} {tool_input.get("path", "")}'.strip()
    if tool_name == "Agent":
        return tool_input.get("prompt", tool_input.get("description", ""))[:500]

    # Generic: try common field names
    for key in ("query", "command", "prompt", "file_path", "path", "description"):
        if key in tool_input and isinstance(tool_input[key], str):
            return tool_input[key][:500]
    return ""




def list_all_jsonl(
    projects_dir: Path,
    project_filter: str | None = None,
) -> dict[str, Path]:
    """List all JSONL files, returning {relative_path: absolute_path}.

    Relative path is like "project-dir/session-id.jsonl".
    """
    files = {}
    if not projects_dir.exists():
        return files

    for proj_entry in sorted(projects_dir.iterdir()):
        if not proj_entry.is_dir():
            continue

        project_name = proj_entry.name
        if project_filter and project_filter not in project_name:
            continue

        for jsonl_file in sorted(proj_entry.glob("*.jsonl")):
            rel = f"{project_name}/{jsonl_file.name}"
            files[rel] = jsonl_file

    return files




def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filename-safe slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:max_len].rstrip('-')


def _extract_readable(content, role: str) -> str:
    """Extract readable text from a message's content field for the markdown export.

    Rules:
    - User/assistant text: include fully
    - Thinking blocks: include (valuable reasoning)
    - Tool use: show tool name + key input, code snippets capped at 50 lines
    - Tool results: show file path for Read, cap Bash output at 30 lines, skip large content
    """
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            bt = block.get("type", "")
            if bt == "text":
                parts.append(block.get("text", ""))
            elif bt == "thinking":
                thinking = block.get("thinking", "")
                if thinking.strip():
                    parts.append(f"*Thinking:* {thinking}")
            elif bt == "tool_use":
                parts.append(_format_tool_use(block))
            elif bt == "tool_result":
                parts.append(_format_tool_result(block))

    return "\n\n".join(p for p in parts if p.strip())


def _format_tool_use(block: dict) -> str:
    """Format a tool_use block for readable markdown."""
    name = block.get("name", "unknown")
    inp = block.get("input", {})
    if not isinstance(inp, dict):
        return f"**[{name}]**"

    canonical = name.capitalize()
    formatters = {
        "Read": lambda i: f"**[Read]** `{i.get('file_path', '')}`",
        "Write": lambda i: f"**[Write]** `{i.get('file_path', '')}`\n```\n{_cap_lines(i.get('content', ''), 50)}\n```",
        "Edit": lambda i: f"**[Edit]** `{i.get('file_path', '')}`\n```diff\n- {_cap_lines(i.get('old_string', ''), 20)}\n+ {_cap_lines(i.get('new_string', ''), 20)}\n```",
        "Bash": lambda i: f"**[Bash]** `{i.get('command', '')}`",
        "Grep": lambda i: f"**[Grep]** `{i.get('pattern', '')}` in `{i.get('path', '.')}`",
        "Glob": lambda i: f"**[Glob]** `{i.get('pattern', '')}` in `{i.get('path', '.')}`",
        "Agent": lambda i: f"**[Agent: {i.get('description', '')}]**\n{_cap_lines(i.get('prompt', ''), 10)}",
    }

    fmt = formatters.get(canonical)
    if fmt:
        return fmt(inp)
    return f"**[{name}]** {_summarize_tool_input(name, inp)}"


def _format_tool_result(block: dict) -> str:
    """Format a tool_result block for readable markdown."""
    is_error = block.get("is_error", False)
    rc = block.get("content", "")

    if isinstance(rc, str):
        if not rc.strip():
            return ""
        text = _cap_lines(rc, 30)
        if is_error:
            return f"**Error:**\n```\n{text}\n```"
        return f"**Result:**\n```\n{text}\n```"

    if isinstance(rc, list):
        parts = []
        for sub in rc:
            if isinstance(sub, dict) and sub.get("type") == "text":
                text = _cap_lines(sub.get("text", ""), 30)
                if text.strip():
                    parts.append(f"```\n{text}\n```")
        if parts:
            prefix = "**Error:**" if is_error else "**Result:**"
            return f"{prefix}\n" + "\n".join(parts)

    return ""


def _cap_lines(text: str, max_lines: int) -> str:
    """Cap text to max_lines, showing first and last lines if truncated."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    head = max_lines - 5
    tail = 5
    return "\n".join(lines[:head] + [f"... ({len(lines) - head - tail} lines truncated) ..."] + lines[-tail:])


def render_session_markdown(
    jsonl_path: Path,
    project_name: str,
    source_name: str = "claude",
    source_jsonl: str = "",
) -> tuple[str, dict]:
    """Render a JSONL session file as readable markdown.

    Returns (markdown_content, metadata_dict).
    Metadata includes: session_id, project, source, source_jsonl, date, message_count, first_prompt.
    """
    from agentkb.chats.sources import get_source

    session_id = jsonl_path.stem
    messages = []
    first_prompt = ""
    first_date = ""
    msg_count = 0

    source = get_source(source_name)
    parsed = source.parse_jsonl(jsonl_path)

    for entry in parsed:
        role = entry.get("role", "")
        content = entry.get("content", "")
        timestamp = entry.get("timestamp", "")

        text = _extract_readable(content, role)
        if not text.strip():
            continue

        msg_count += 1

        if role == "user" and not first_prompt:
            # Get first user text (not tool results)
            if isinstance(content, str):
                first_prompt = content.strip()
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        first_prompt = block.get("text", "").strip()
                        break
            if not first_date:
                first_date = timestamp[:10] if timestamp else ""

        label = "User" if role == "user" else "Assistant"
        time_str = ""
        if timestamp:
            # Format: "2026-04-04T14:30:18.649Z" -> "14:30"
            t = timestamp[11:16] if len(timestamp) >= 16 else ""
            d = timestamp[:10] if len(timestamp) >= 10 else ""
            if t:
                time_str = f" *({d} {t})*"
        messages.append(f"**{label}:**{time_str}\n{text}")

    if not messages:
        return "", {}

    first_prompt_short = first_prompt[:200] if first_prompt else "untitled"
    title = next((l.strip()[:100] for l in first_prompt.split("\n") if l.strip()), "untitled")

    # Build frontmatter
    lines = [
        "---",
        f"session_id: {session_id}",
        f"project: {project_name}",
        f"source: {source_name}",
        f"source_jsonl: {source_jsonl}",
        f"date: {first_date}",
        f"messages: {msg_count}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Project:** {project_name}",
        f"**Source:** {source_name}",
        f"**Date:** {first_date}",
        f"**Messages:** {msg_count}",
        "",
        "---",
        "",
    ]

    lines.append("\n\n---\n\n".join(messages))

    metadata = {
        "session_id": session_id,
        "project": project_name,
        "source": source_name,
        "source_jsonl": source_jsonl,
        "date": first_date,
        "messages": msg_count,
        "first_prompt": first_prompt_short,
        "title": title,
    }

    return "\n".join(lines), metadata


def export_readable(
    sessions_dir: Path,
    readable_dir: Path,
    project_filter: str | None = None,
) -> dict:
    """Generate readable markdown files from JSONL sessions.

    Iterates over source subdirectories (sessions/claude/, sessions/pi/, etc.),
    renders each session with the appropriate source parser, and writes merged
    readable markdown to a single output directory.

    Also generates _index.md with links to all sessions.
    Incremental: skips sessions whose JSONL hasn't changed.
    """
    from agentkb.chats.sources import SOURCES

    readable_dir.mkdir(parents=True, exist_ok=True)

    # Collect all source files across all source subdirectories
    # Keys are "{source}/{project}/{session}.jsonl" to avoid collisions
    source_files: dict[str, tuple[Path, str]] = {}  # rel_key -> (abs_path, source_name)
    for source_subdir in sorted(sessions_dir.iterdir()) if sessions_dir.exists() else []:
        if not source_subdir.is_dir():
            continue
        src_name = source_subdir.name
        if src_name not in SOURCES:
            continue
        for rel_path, abs_path in list_all_jsonl(source_subdir, project_filter=project_filter).items():
            rel_key = f"{src_name}/{rel_path}"
            source_files[rel_key] = (abs_path, src_name)

    # Load existing state to detect changes
    state_path = readable_dir / "_state.json"
    old_state = {}
    if state_path.exists():
        try:
            old_state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    new_state = {}
    all_metadata = []
    generated = 0
    skipped = 0

    for rel_key, (src_path, src_name) in source_files.items():
        src_hash = file_hash(src_path)
        new_state[rel_key] = src_hash

        # Parse project name: rel_key is "{source}/{project}/{session}.jsonl"
        parts = rel_key.split("/")
        project_name = parts[1] if len(parts) >= 3 else parts[0]
        session_id = src_path.stem

        # Check if we already generated this version
        if old_state.get(rel_key) == src_hash:
            # Load existing metadata from the readable file if it exists
            for md_file in readable_dir.rglob(f"*{session_id[:8]}*.md"):
                if md_file.name != "_index.md":
                    try:
                        text = md_file.read_text()
                        from agentkb.utils import parse_frontmatter
                        fm = parse_frontmatter(text)
                        all_metadata.append({
                            "session_id": fm.get("session_id", session_id),
                            "project": fm.get("project", project_name),
                            "source": fm.get("source", src_name),
                            "date": str(fm.get("date", "")),
                            "messages": fm.get("messages", 0),
                            "first_prompt": "",
                            "title": fm.get("session_id", session_id),
                            "filename": str(md_file.relative_to(readable_dir)),
                        })
                    except Exception:
                        pass
                    break
            skipped += 1
            continue

        # Reconstruct original source path for traceability
        source_obj = SOURCES[src_name]
        orig_dir = source_obj.source_dir()
        # rel_path within the source is everything after "{source}/"
        inner_rel = "/".join(rel_key.split("/")[1:])
        orig_jsonl = str(orig_dir / inner_rel) if orig_dir else ""

        # Generate readable markdown
        md_content, metadata = render_session_markdown(
            src_path, project_name,
            source_name=src_name,
            source_jsonl=orig_jsonl,
        )
        if not md_content or not metadata:
            skipped += 1
            continue

        # Determine output path: readable/{YYYY-MM}/{date}--{source}--{project}--{slug}.md
        date = metadata.get("date", "unknown")
        month = date[:7] if len(date) >= 7 else "unknown"
        slug = _slugify(metadata.get("title", "untitled"))
        proj_slug = project_name.strip("-").replace("/", "-")
        if len(proj_slug) > 40:
            proj_slug = proj_slug[-40:]

        filename = f"{date}--{src_name}--{proj_slug}--{slug}.md"
        month_dir = readable_dir / month
        month_dir.mkdir(parents=True, exist_ok=True)

        out_path = month_dir / filename
        out_path.write_text(md_content)

        metadata["filename"] = f"{month}/{filename}"
        all_metadata.append(metadata)
        generated += 1

    # Generate _index.md
    all_metadata.sort(key=lambda m: m.get("date", ""), reverse=True)
    index_lines = ["# Chat History", ""]

    current_month = ""
    for meta in all_metadata:
        date = meta.get("date", "")
        month = date[:7] if len(date) >= 7 else "unknown"
        if month != current_month:
            current_month = month
            index_lines.append(f"## {month}")
            index_lines.append("")

        fname = meta.get("filename", "")
        title = meta.get("title", "untitled")
        project = meta.get("project", "")
        source = meta.get("source", "")
        msgs = meta.get("messages", 0)
        index_lines.append(f"- [{title}]({fname}) — {source}/{project}, {msgs} messages")

    index_lines.append("")
    (readable_dir / "_index.md").write_text("\n".join(index_lines))

    # Save state
    state_path.write_text(json.dumps(new_state, indent=2))

    return {
        "generated": generated,
        "skipped": skipped,
        "total": len(source_files),
    }


def export_sessions(
    source_dir: Path,
    dest_dir: Path,
    project_filter: str | None = None,
) -> dict:
    """Copy JSONL files from source (e.g. ~/.claude/projects/) to dest (agentkb-owned sessions/).

    Incremental: only copies files whose content hash has changed.
    Returns stats dict.
    """
    source_files = list_all_jsonl(source_dir, project_filter=project_filter)

    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    for rel_path, src_path in source_files.items():
        dst_path = dest_dir / rel_path
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # Skip if dest exists and has same content hash
        if dst_path.exists():
            if file_hash(src_path) == file_hash(dst_path):
                skipped += 1
                continue

        shutil.copy2(src_path, dst_path)
        copied += 1

    return {
        "copied": copied,
        "skipped": skipped,
        "total": len(source_files),
    }


def _list_all_md(root: Path, project_filter: str | None = None) -> dict[str, Path]:
    """List all markdown files in readable directory, returning {relative_path: absolute_path}."""
    files = {}
    if not root.exists():
        return files
    for md_file in sorted(root.rglob("*.md")):
        if md_file.name.startswith("_"):
            continue
        rel = str(md_file.relative_to(root))
        if project_filter and project_filter not in rel:
            continue
        files[rel] = md_file
    return files


def _make_chat_structured_text(title: str, section: str, tags: list, content: str) -> str:
    """Generate structured text for embedding a chat chunk."""
    parts = [f"[chats] {title}"]
    if section and section != "(full page)":
        parts[0] += f" > {section}"
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    parts.append("")
    parts.append(content)
    return "\n".join(parts)


def build_chat_index(
    projects_dir: Path,
    index_dir: Path,
    model_name: str | None = None,
    incremental: bool = True,
    project_filter: str | None = None,
    tracked_only: bool = False,
    json_output: bool = False,
) -> dict:
    """Build the chat history search index from readable markdown files.

    Truly incremental: only parses and encodes changed/new files.

    Args:
        projects_dir: Path to the readable/ directory (not JSONL).
        tracked_only: If True, only update files already in the index.
    """
    from agentkb.utils import chunk_markdown
    from agentkb.encoder import DEFAULT_MODEL
    effective_model = model_name or DEFAULT_MODEL

    store = IndexStore(index_dir)

    old_state = {}
    if incremental and store.exists():
        old_state = store.load_state()

    # Model change forces full rebuild
    if old_state and old_state.get("__model__") != effective_model:
        echo_status(f"[agentkb] Model changed to {effective_model}, rebuilding index...", json_output=json_output)
        old_state = {}
        tracked_only = False
        if store.exists():
            store.clear()

    if tracked_only and old_state:
        all_files = {}
        for rel_path in old_state:
            if rel_path.startswith("__"):
                continue
            abs_path = projects_dir / rel_path
            if abs_path.exists():
                all_files[rel_path] = abs_path
    else:
        all_files = _list_all_md(projects_dir, project_filter=project_filter)

    new_state = {"__model__": effective_model}
    for rel_path, abs_path in all_files.items():
        new_state[rel_path] = file_hash(abs_path)

    if not all_files and not old_state:
        echo_status("[agentkb] No chat history found.", json_output=json_output)
        return {"sessions_parsed": 0, "chunks_indexed": 0}

    if old_state:
        changed_files = {f for f, h in new_state.items()
                         if not f.startswith("__") and old_state.get(f) != h}
        new_files = {f for f in new_state
                     if not f.startswith("__") and f not in old_state}
        removed_files = {f for f in old_state
                         if not f.startswith("__") and f not in new_state}
        if tracked_only:
            new_files = set()
            removed_files = set()
        files_to_process = changed_files | new_files

        if not files_to_process and not removed_files:
            store.close()
            return {"sessions_parsed": 0, "chunks_indexed": 0, "up_to_date": True}

        echo_status(
            f"[agentkb] Chat index: {len(new_files)} new, "
            f"{len(changed_files)} changed, {len(removed_files)} removed",
            json_output=json_output,
        )
    else:
        files_to_process = set(all_files.keys())
        removed_files = set()

    if not store.exists():
        store.create()

    stale_files = (files_to_process & set(old_state.keys())) | removed_files
    if stale_files:
        store.delete_documents_by_file(stale_files)

    # Chunk the changed readable markdown files
    all_chunks = []
    for rel_path in files_to_process:
        abs_path = all_files[rel_path]
        raw_chunks = chunk_markdown(abs_path, relative_to=projects_dir)
        all_chunks.extend(raw_chunks)

    echo_status(
        f"  Parsed {len(files_to_process)} sessions, found {len(all_chunks)} new chunks",
        json_output=json_output,
    )

    if all_chunks:
        encoder = get_encoder(model_name=model_name)

        # Build structured text and documents
        docs = []
        texts = []
        for raw in all_chunks:
            structured = _make_chat_structured_text(
                raw["title"], raw["section"], raw["tags"], raw["content"]
            )
            texts.append(structured)
            docs.append({
                "collection": "chats",
                "file": raw["file"],
                "line": raw["line"],
                "name": raw["title"],
                "unit_type": "chunk",
                "content": structured,
                "raw_content": raw["content"],
                "title": raw["title"],
                "section": raw["section"],
                "tags": raw.get("tags", []),
            })

        echo_status(f"[agentkb] Encoding {len(texts)} chat chunks with ColBERT...", json_output=json_output)
        embeddings = encoder.encode_documents(texts)

        doc_ids = store.add_documents(docs)

        echo_status("[agentkb] Updating PLAID index...", json_output=json_output)
        store.append_plaid_index(doc_ids, embeddings)

    if tracked_only and old_state:
        merged_state = dict(old_state)
        merged_state.update(new_state)
        store.save_state(merged_state)
    else:
        store.save_state(new_state)
    store.close()

    return {
        "sessions_parsed": len(files_to_process),
        "chunks_indexed": len(all_chunks),
    }


def chat_index_is_stale(readable_dir: Path, index_dir: Path) -> bool:
    """Check if any tracked readable markdown files have changed since last index build.

    Only checks files already in the index state — does NOT scan for new files.
    """
    state_file = index_dir / "state.json"
    if not state_file.exists():
        return False

    index_mtime = state_file.stat().st_mtime

    if not readable_dir.exists():
        return False

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return True

    # Check model mismatch
    from agentkb.encoder import DEFAULT_MODEL
    if state.get("__model__") != DEFAULT_MODEL:
        return True

    for rel_path in state:
        if rel_path.startswith("__"):
            continue
        abs_path = readable_dir / rel_path
        if not abs_path.exists():
            return True
        if abs_path.stat().st_mtime > index_mtime:
            return True

    return False


def export_all_sessions(
    sessions_dir: Path,
    project_filter: str | None = None,
) -> dict:
    """Export sessions from all registered sources to sessions/{source}/.

    Each source's JSONL files are copied into a source-named subdirectory
    (e.g. sessions/claude/, sessions/pi/).
    """
    from agentkb.chats.sources import get_all_sources

    total = {"copied": 0, "skipped": 0, "total": 0}
    for source in get_all_sources():
        src_dir = source.source_dir()
        if src_dir is None or not src_dir.exists():
            continue
        dest = sessions_dir / source.name
        stats = export_sessions(src_dir, dest, project_filter=project_filter)
        total["copied"] += stats["copied"]
        total["skipped"] += stats["skipped"]
        total["total"] += stats["total"]
    return total


def migrate_sessions_layout(sessions_dir: Path) -> bool:
    """Migrate flat sessions/{project}/ layout to sessions/{source}/{project}/.

    Detects the old layout by checking if any immediate subdirectory contains
    .jsonl files (in the new layout, immediate children are source dirs like
    'claude/' which contain project dirs, not .jsonl files directly).

    Returns True if migration was performed.
    """
    if not sessions_dir.exists():
        return False

    from agentkb.chats.sources import SOURCES
    known_sources = set(SOURCES.keys())

    # Check each child directory
    needs_migration = False
    for child in sessions_dir.iterdir():
        if child.is_dir() and child.name not in known_sources:
            if any(child.glob("*.jsonl")):
                needs_migration = True
                break

    if not needs_migration:
        return False

    # Move all non-source-named directories under claude/
    claude_dir = sessions_dir / "claude"
    claude_dir.mkdir(exist_ok=True)

    for child in list(sessions_dir.iterdir()):
        if child.is_dir() and child.name not in known_sources:
            dest = claude_dir / child.name
            child.rename(dest)

    # Invalidate readable output so everything re-renders with new source metadata.
    # Delete old readable files (they have old naming without source tag) and state.
    readable_dir = sessions_dir.parent / "readable"
    if readable_dir.exists():
        for md_file in readable_dir.rglob("*.md"):
            md_file.unlink()
        state = readable_dir / "_state.json"
        if state.exists():
            state.unlink()

    return True
