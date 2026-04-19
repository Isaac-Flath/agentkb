"""Chat pipeline: copy JSONL from agent sources, render readable markdown, layout migrations."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from agentkb.utils import file_hash


# --- Tool input summarization ---


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

    for key in ("query", "command", "prompt", "file_path", "path", "description"):
        if key in tool_input and isinstance(tool_input[key], str):
            return tool_input[key][:500]
    return ""


# --- File discovery ---


def list_all_jsonl(
    projects_dir: Path,
    project_filter: str | None = None,
) -> dict[str, Path]:
    """List all JSONL files under a source dir, keyed by "project/session.jsonl"."""
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
            files[f"{project_name}/{jsonl_file.name}"] = jsonl_file

    return files


# --- Readable markdown rendering ---


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filename-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:max_len].rstrip('-')


def _cap_lines(text: str, max_lines: int) -> str:
    """Cap text to max_lines, showing first and last lines if truncated."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    head = max_lines - 5
    tail = 5
    return "\n".join(lines[:head] + [f"... ({len(lines) - head - tail} lines truncated) ..."] + lines[-tail:])


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
        match block:
            case str():
                parts.append(block)
            case dict():
                match block.get("type", ""):
                    case "text":
                        parts.append(block.get("text", ""))
                    case "thinking":
                        thinking = block.get("thinking", "")
                        if thinking.strip():
                            parts.append(f"*Thinking:* {thinking}")
                    case "tool_use":
                        parts.append(_format_tool_use(block))
                    case "tool_result":
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

    match rc:
        case str():
            if not rc.strip():
                return ""
            text = _cap_lines(rc, 30)
            if is_error:
                return f"**Error:**\n```\n{text}\n```"
            return f"**Result:**\n```\n{text}\n```"

        case list():
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

        case _:
            return ""


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
            t = timestamp[11:16] if len(timestamp) >= 16 else ""
            d = timestamp[:10] if len(timestamp) >= 10 else ""
            if t:
                time_str = f" *({d} {t})*"
        messages.append(f"**{label}:**{time_str}\n{text}")

    if not messages:
        return "", {}

    first_prompt_short = first_prompt[:200] if first_prompt else "untitled"
    title = next((l.strip()[:100] for l in first_prompt.split("\n") if l.strip()), "untitled")

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


# --- Copy + render pipeline ---


def export_sessions(
    source_dir: Path,
    dest_dir: Path,
    project_filter: str | None = None,
) -> dict:
    """Copy JSONL from source (e.g. ~/.claude/projects/) to dest.

    Incremental: only copies files whose content hash has changed.
    """
    source_files = list_all_jsonl(source_dir, project_filter=project_filter)
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    for rel_path, src_path in source_files.items():
        dst_path = dest_dir / rel_path
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if dst_path.exists() and file_hash(src_path) == file_hash(dst_path):
            skipped += 1
            continue

        shutil.copy2(src_path, dst_path)
        copied += 1

    return {"copied": copied, "skipped": skipped, "total": len(source_files)}


def export_all_sessions(
    sessions_dir: Path,
    project_filter: str | None = None,
) -> dict:
    """Export sessions from all registered chat sources into sessions/{source}/."""
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
    from agentkb.utils import parse_frontmatter

    readable_dir.mkdir(parents=True, exist_ok=True)

    # Collect source files keyed as "{source}/{project}/{session}.jsonl"
    source_files: dict[str, tuple[Path, str]] = {}
    for source_subdir in sorted(sessions_dir.iterdir()) if sessions_dir.exists() else []:
        if not source_subdir.is_dir():
            continue
        src_name = source_subdir.name
        if src_name not in SOURCES:
            continue
        for rel_path, abs_path in list_all_jsonl(source_subdir, project_filter=project_filter).items():
            source_files[f"{src_name}/{rel_path}"] = (abs_path, src_name)

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

        parts = rel_key.split("/")
        project_name = parts[1] if len(parts) >= 3 else parts[0]
        session_id = src_path.stem

        if old_state.get(rel_key) == src_hash:
            for md_file in readable_dir.rglob(f"*{session_id[:8]}*.md"):
                if md_file.name != "_index.md":
                    try:
                        fm = parse_frontmatter(md_file.read_text())
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

        source_obj = SOURCES[src_name]
        orig_dir = source_obj.source_dir()
        inner_rel = "/".join(rel_key.split("/")[1:])
        orig_jsonl = str(orig_dir / inner_rel) if orig_dir else ""

        md_content, metadata = render_session_markdown(
            src_path, project_name,
            source_name=src_name,
            source_jsonl=orig_jsonl,
        )
        if not md_content or not metadata:
            skipped += 1
            continue

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
        index_lines.append(
            f"- [{meta.get('title', 'untitled')}]({meta.get('filename', '')}) — "
            f"{meta.get('source', '')}/{meta.get('project', '')}, "
            f"{meta.get('messages', 0)} messages"
        )
    index_lines.append("")
    (readable_dir / "_index.md").write_text("\n".join(index_lines))

    state_path.write_text(json.dumps(new_state, indent=2))

    return {"generated": generated, "skipped": skipped, "total": len(source_files)}


# --- Layout migration ---


def migrate_sessions_layout(sessions_dir: Path) -> bool:
    """Migrate flat sessions/{project}/ layout to sessions/{source}/{project}/.

    Old layout: sessions/<project>/*.jsonl (Claude only, before Pi support).
    New layout: sessions/<source>/<project>/*.jsonl.

    Detected by finding a direct child of sessions/ that isn't a known source
    name but contains .jsonl files. Returns True if a migration ran.
    """
    if not sessions_dir.exists():
        return False

    from agentkb.chats.sources import SOURCES
    known_sources = set(SOURCES.keys())

    needs_migration = any(
        child.is_dir() and child.name not in known_sources and any(child.glob("*.jsonl"))
        for child in sessions_dir.iterdir()
    )
    if not needs_migration:
        return False

    claude_dir = sessions_dir / "claude"
    claude_dir.mkdir(exist_ok=True)
    for child in list(sessions_dir.iterdir()):
        if child.is_dir() and child.name not in known_sources:
            child.rename(claude_dir / child.name)

    # Invalidate readable output — old files were named without a source tag.
    readable_dir = sessions_dir.parent / "readable"
    if readable_dir.exists():
        for md_file in readable_dir.rglob("*.md"):
            md_file.unlink()
        state = readable_dir / "_state.json"
        if state.exists():
            state.unlink()

    return True
