"""CLI for the skills store — git-managed agent skills, no indexing."""

from pathlib import Path

import click

from agentkb.config import paths, Settings
from agentkb.skills import find_skills


@click.group()
def skills():
    """Manage agent skills (git-synced, not indexed)."""
    pass


@skills.command()
def status():
    """Show skills store status."""
    skills_dir = paths.skills_dir()
    s = Settings()
    remote = s.get("skills_remote")

    click.echo("[agentkb] Skills store:")
    if remote:
        click.echo(f"  Remote: {remote}")
    else:
        click.echo("  Remote: not configured")
        click.echo('  Set with: agentkb settings set skills_remote "git@github.com:user/skills.git"')

    click.echo(f"  Local:  {skills_dir}")

    if not skills_dir.exists():
        if remote:
            click.echo("  Status: not cloned (run `agentkb sync pull`)")
        else:
            click.echo("  Status: not set up")
        return

    skill_dirs = find_skills(skills_dir)
    click.echo(f"  Skills: {len(skill_dirs)}")
    for sd in sorted(skill_dirs):
        click.echo(f"    - {sd.parent.name}")


@skills.command("list")
def list_skills():
    """List installed skills."""
    skills_dir = paths.skills_dir()
    if not skills_dir.exists():
        click.echo("[agentkb] No skills installed. Configure skills_remote and run `agentkb sync pull`.")
        return

    skill_dirs = find_skills(skills_dir)
    if not skill_dirs:
        click.echo(f"[agentkb] No skills found in {skills_dir}")
        return

    for sd in sorted(skill_dirs):
        desc = _read_skill_description(sd)
        if desc:
            click.echo(f"  {sd.parent.name} — {desc}")
        else:
            click.echo(f"  {sd.parent.name}")


@skills.command()
def path():
    """Print the skills directory path (for use with --add-dir)."""
    click.echo(paths.skills_dir())


def _read_skill_description(skill_md: Path) -> str | None:
    """Extract description from SKILL.md YAML frontmatter."""
    try:
        text = skill_md.read_text()
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    frontmatter = text[3:end]
    for line in frontmatter.splitlines():
        line = line.strip()
        if line.startswith("description:"):
            return line[len("description:"):].strip().strip('"').strip("'")
    return None
