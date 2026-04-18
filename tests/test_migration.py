"""Tests for sessions directory migration (flat -> per-source layout)."""

from agentkb.chats.parser import migrate_sessions_layout


def test_migration_moves_projects_under_claude(tmp_path):
    """Old layout sessions/{project}/ migrates to sessions/claude/{project}/."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    proj = sessions_dir / "my-project"
    proj.mkdir()
    (proj / "s1.jsonl").write_text("{}")

    # Create readable dir with old-format files that should be cleaned up
    readable_dir = tmp_path / "readable"
    readable_dir.mkdir()
    month_dir = readable_dir / "2026-04"
    month_dir.mkdir()
    old_md = month_dir / "2026-04-01--my-project--old-session.md"
    old_md.write_text("old content")
    state_file = readable_dir / "_state.json"
    state_file.write_text('{"old": "data"}')

    assert migrate_sessions_layout(sessions_dir) is True
    assert (sessions_dir / "claude" / "my-project" / "s1.jsonl").exists()
    assert not (sessions_dir / "my-project").exists()
    # Readable state and old markdown should be deleted
    assert not state_file.exists()
    assert not old_md.exists()


def test_migration_noop_if_already_migrated(tmp_path):
    """No-op if directory already has source-named subdirs with project subdirs."""
    claude = tmp_path / "claude"
    claude.mkdir()
    proj = claude / "proj"
    proj.mkdir()
    (proj / "s1.jsonl").write_text("{}")

    assert migrate_sessions_layout(tmp_path) is False


def test_migration_noop_if_empty(tmp_path):
    """No-op for empty directory."""
    assert migrate_sessions_layout(tmp_path) is False


def test_migration_noop_if_nonexistent(tmp_path):
    """No-op for nonexistent directory."""
    assert migrate_sessions_layout(tmp_path / "does-not-exist") is False


def test_migration_preserves_multiple_projects(tmp_path):
    """All project directories get moved under claude/."""
    for name in ["project-a", "project-b", "project-c"]:
        d = tmp_path / name
        d.mkdir()
        (d / "session.jsonl").write_text("{}")

    migrate_sessions_layout(tmp_path)

    for name in ["project-a", "project-b", "project-c"]:
        assert (tmp_path / "claude" / name / "session.jsonl").exists()
        assert not (tmp_path / name).exists()
