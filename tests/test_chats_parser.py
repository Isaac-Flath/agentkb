"""Tests for agentkb.chats.parser — chat export, readable rendering, tool formatting.

chats/parser.py handles the pipeline that turns raw Claude Code JSONL conversations
into searchable content. The pipeline has three stages:
1. export_sessions: copy JSONL from ~/.claude/projects/ to agentkb-owned storage
2. export_readable: convert JSONL to human-readable markdown (with tool formatting)
3. build_chat_index: chunk and embed the readable markdown for search

The readable markdown format is important — it's both what gets indexed for search
and what humans read when browsing chat history. The tool formatting functions
control how tool_use/tool_result blocks appear in that markdown.
"""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path

import agentkb.chats.parser as chats_parser
from agentkb.chats.parser import (
    _summarize_tool_input,
    _cap_lines,
    _slugify,
    _extract_readable,
    _format_tool_use,
    _format_tool_result,
    render_session_markdown,
    list_all_jsonl,
    export_sessions,
    export_readable,
)


# --- _summarize_tool_input ---
# When converting JSONL to readable markdown, tool_use blocks need to be
# condensed into something scannable. A Bash tool call has a command, a Read
# has a file_path, a Grep has a pattern + path. _summarize_tool_input extracts
# the most useful field from each tool's input dict so the readable markdown
# shows what the tool did without the full JSON blob.


def test_summarize_bash():
    """Extracts command from Bash tool input."""
    assert _summarize_tool_input("Bash", {"command": "ls -la"}) == "ls -la"


def test_summarize_read():
    """Extracts file_path from Read tool input."""
    assert _summarize_tool_input("Read", {"file_path": "/tmp/a.py"}) == "/tmp/a.py"


def test_summarize_grep():
    """Combines pattern and path from Grep tool input."""
    result = _summarize_tool_input("Grep", {"pattern": "TODO", "path": "src/"})
    assert "TODO" in result
    assert "src/" in result


def test_summarize_generic():
    """Falls back to common field names for unknown tools."""
    assert _summarize_tool_input("Custom", {"query": "something"}) == "something"


def test_summarize_non_dict():
    """Returns empty string for non-dict input."""
    assert _summarize_tool_input("Bash", "just a string") == ""


# --- _cap_lines ---
# Tool results can be huge (e.g., a Bash command that dumps 500 lines of output).
# _cap_lines truncates long text while keeping the head and tail visible, with
# a "... (N lines truncated) ..." marker in the middle. This keeps the readable
# markdown from being dominated by tool output.


def test_cap_lines_short():
    """Returns text unchanged when under the limit."""
    assert _cap_lines("a\nb\nc", 5) == "a\nb\nc"


def test_cap_lines_truncates():
    """Truncates long text, keeping head and tail with a marker."""
    text = "\n".join(f"line {i}" for i in range(50))
    result = _cap_lines(text, 10)
    assert "line 0" in result  # head preserved
    assert "line 49" in result  # tail preserved
    assert "truncated" in result


# --- _slugify ---
# Readable markdown files are named like "2024-06-15--my-project--how-to-rebase.md".
# _slugify converts the session's first prompt into that filename-safe slug part.
# It lowercases, strips special chars, and truncates to max_len.


def test_slugify_basic():
    """Converts title to lowercase hyphenated slug."""
    assert _slugify("Hello World") == "hello-world"


def test_slugify_special_chars():
    """Strips non-word characters."""
    assert _slugify("What's the plan?!") == "whats-the-plan"


def test_slugify_max_length():
    """Respects max_len limit."""
    result = _slugify("a " * 100, max_len=10)
    assert len(result) <= 10


# --- _extract_readable ---
# Claude Code JSONL messages have a "content" field that can be a plain string
# or a list of typed blocks (text, thinking, tool_use, tool_result). _extract_readable
# walks through these blocks and converts each type into a readable markdown
# representation. Thinking blocks are included (they contain valuable reasoning),
# tool_use blocks show what tool was called, tool_result blocks show the output.


def test_extract_readable_string():
    """String content is returned as-is."""
    assert _extract_readable("Hello", "user") == "Hello"


def test_extract_readable_text_block():
    """Extracts text from content block list."""
    content = [{"type": "text", "text": "Hello world"}]
    assert _extract_readable(content, "user") == "Hello world"


def test_extract_readable_thinking():
    """Includes thinking blocks prefixed with '*Thinking:*'."""
    content = [{"type": "thinking", "thinking": "Let me think..."}]
    result = _extract_readable(content, "assistant")
    assert "*Thinking:*" in result
    assert "Let me think..." in result


def test_extract_readable_tool_use():
    """Formats tool use blocks with tool name."""
    content = [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]
    result = _extract_readable(content, "assistant")
    assert "[Bash]" in result
    assert "ls" in result


# --- _format_tool_use ---
# Each tool type gets its own formatting. Read shows the file path, Edit shows
# a diff-style before/after, Bash shows the command, Grep shows pattern + path.
# This makes the readable markdown scannable — you can quickly see what the
# assistant did without parsing raw JSON.


def test_format_tool_use_read():
    """Read tool shows file path."""
    block = {"name": "Read", "input": {"file_path": "/tmp/test.py"}}
    result = _format_tool_use(block)
    assert "[Read]" in result
    assert "/tmp/test.py" in result


def test_format_tool_use_edit():
    """Edit tool shows file path and diff."""
    block = {"name": "Edit", "input": {
        "file_path": "/tmp/test.py",
        "old_string": "old code",
        "new_string": "new code",
    }}
    result = _format_tool_use(block)
    assert "[Edit]" in result
    assert "old code" in result
    assert "new code" in result


# --- _format_tool_result ---
# Tool results (the output that comes back from tool execution) are formatted
# into code blocks. Error results get an "Error:" label. Large results are
# capped by _cap_lines to avoid bloating the readable markdown.


def test_format_tool_result_string():
    """String result gets wrapped in a code block."""
    block = {"content": "file contents here"}
    result = _format_tool_result(block)
    assert "```" in result
    assert "file contents here" in result


def test_format_tool_result_error():
    """Error results are labeled."""
    block = {"content": "command not found", "is_error": True}
    result = _format_tool_result(block)
    assert "Error" in result


def test_format_tool_result_empty():
    """Empty content returns empty string."""
    assert _format_tool_result({"content": ""}) == ""


# --- render_session_markdown ---
# This is the main function that converts a single JSONL session file into
# readable markdown. It extracts the first user prompt as the title, parses
# timestamps, and renders all messages with User/Assistant labels. The output
# includes YAML frontmatter with session metadata (session_id, project, date,
# message count) which is used for the chat history index.


def test_render_session_markdown(tmp_path):
    """Renders a JSONL session into readable markdown with frontmatter."""
    jsonl = tmp_path / "abc123.jsonl"
    lines = [
        json.dumps({"type": "user", "timestamp": "2024-06-15T10:30:00Z",
                     "message": {"content": "How do I use git rebase?"}}),
        json.dumps({"type": "assistant", "timestamp": "2024-06-15T10:30:05Z",
                     "message": {"content": "Git rebase replays commits..."}}),
    ]
    jsonl.write_text("\n".join(lines))

    md, meta = render_session_markdown(jsonl, "my-project")
    assert meta["session_id"] == "abc123"
    assert meta["project"] == "my-project"
    assert meta["date"] == "2024-06-15"
    assert meta["messages"] == 2
    assert "git rebase" in md.lower()
    assert "**User:**" in md
    assert "**Assistant:**" in md


def test_render_session_empty(tmp_path):
    """Empty JSONL produces empty output."""
    jsonl = tmp_path / "empty.jsonl"
    jsonl.write_text("")
    md, meta = render_session_markdown(jsonl, "proj")
    assert md == ""
    assert meta == {}


# --- list_all_jsonl ---
# Claude Code stores conversations as JSONL files in ~/.claude/projects/,
# organized in project subdirectories. list_all_jsonl discovers all these files
# and returns them as {relative_path: absolute_path}. The relative path
# ("project-name/session-id.jsonl") is used as the key for incremental export.


def test_list_all_jsonl(tmp_path):
    """Discovers JSONL files organized in project subdirectories."""
    proj = tmp_path / "my-project"
    proj.mkdir()
    (proj / "session1.jsonl").write_text("{}")
    (proj / "session2.jsonl").write_text("{}")
    (tmp_path / "other-proj").mkdir()
    (tmp_path / "other-proj" / "session3.jsonl").write_text("{}")

    files = list_all_jsonl(tmp_path)
    assert len(files) == 3
    assert "my-project/session1.jsonl" in files


def test_list_all_jsonl_with_filter(tmp_path):
    """project_filter restricts to matching project directories."""
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "s.jsonl").write_text("{}")
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "s.jsonl").write_text("{}")

    files = list_all_jsonl(tmp_path, project_filter="alpha")
    assert len(files) == 1


# --- export_sessions ---
# export_sessions copies JSONL files from Claude Code's directory to agentkb's
# own sessions/ directory. This is incremental — it uses file_hash to skip files
# that haven't changed. Having agentkb's own copy means the data can be synced
# via git (agentkb sync push/pull) independently of Claude Code.


def test_export_sessions(tmp_path):
    """Copies JSONL files from source to dest, skipping unchanged ones."""
    src = tmp_path / "source"
    dst = tmp_path / "dest"
    proj = src / "proj"
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text('{"type": "user"}')

    stats = export_sessions(src, dst)
    assert stats["copied"] == 1
    assert (dst / "proj" / "s1.jsonl").exists()

    # Running again should skip (same content hash)
    stats2 = export_sessions(src, dst)
    assert stats2["copied"] == 0
    assert stats2["skipped"] == 1


class _FakeEncoder:
    def encode_documents(self, texts):
        return [[0.0] for _ in texts]


class _FakeStore:
    def __init__(self, index_dir):
        self.index_dir = index_dir

    def exists(self):
        return False

    def load_state(self):
        return {}

    def clear(self):
        pass

    def create(self):
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def delete_documents_by_file(self, _files):
        pass

    def add_documents(self, docs):
        return list(range(len(docs)))

    def append_plaid_index(self, _doc_ids, _embeddings):
        pass

    def save_state(self, _state):
        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.index_dir / "state.json").write_text("{}")

    def close(self):
        pass


def test_build_chat_index_json_output_writes_progress_to_stderr(monkeypatch, tmp_path):
    """json_output routes chat indexing progress to stderr, not stdout."""
    readable_dir = tmp_path / "readable" / "proj"
    readable_dir.mkdir(parents=True)
    (readable_dir / "session.md").write_text("---\ntitle: Session\n---\n\n# Topic\n\nDiscussion")

    monkeypatch.setattr(chats_parser, "IndexStore", _FakeStore)
    monkeypatch.setattr(chats_parser, "get_encoder", lambda model_name=None: _FakeEncoder())

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        stats = chats_parser.build_chat_index(
            tmp_path / "readable",
            tmp_path / ".index",
            json_output=True,
        )

    assert stats["sessions_parsed"] == 1
    assert stats["chunks_indexed"] == 1
    assert stdout.getvalue() == ""
    assert "Parsed 1 sessions, found 1 new chunks" in stderr.getvalue()
    assert "Encoding 1 chat chunks with ColBERT" in stderr.getvalue()
    assert "Updating PLAID index" in stderr.getvalue()
