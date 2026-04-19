"""Skills store: git-synced SKILL.md directories loaded by Claude Code via ``--add-dir``.

No search index — agentkb only manages the filesystem presence of skills.
"""

from __future__ import annotations

from pathlib import Path

from agentkb.config import paths, Settings


def find_skills(root: Path) -> list[Path]:
    """Return every ``SKILL.md`` file under ``root``."""
    return list(root.rglob("SKILL.md"))


def status_lines() -> list[str]:
    """Return the ``agentkb status`` output for this store."""
    skills_dir = paths.skills_dir()
    if skills_dir.exists():
        skill_files = find_skills(skills_dir)
        return [f"  Skills: {len(skill_files)} installed ({skills_dir})"]

    if Settings().get("skills_remote"):
        return ["  Skills: not cloned (run `agentkb sync pull`)"]
    return ["  Skills: not configured (set skills_remote)"]
