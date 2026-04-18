---
title: Skills
description: Agent skills managed by git, loaded by Claude Code via --add-dir.
order: 4
---

# Skills

The skills store manages agent skill directories — SKILL.md files with scripts, references, and templates — synced via git. Unlike the other stores, skills are not indexed or searched. They're loaded directly by Claude Code via `--add-dir`.

The wiki is knowledge (what you've learned). Skills are procedures (how to do things). Both make the agent more capable, but through different mechanisms: the wiki feeds the search pipeline, skills feed Claude Code's skill system.

## Setup

```bash
# Point at your skills repo
agentkb settings set skills_remote "git@github.com:youruser/my-skills.git"

# Pull (clones on first run)
agentkb sync pull

# Tell Claude Code where to find them
alias claude='claude --add-dir $(agentkb store skills path)'
```

## Commands

```bash
agentkb store skills status        # show skills store config and count
agentkb store skills list          # list installed skills with descriptions
agentkb store skills path          # print the skills directory (for --add-dir)
```

## Skill Format

Each skill is a directory containing a `SKILL.md` file with YAML frontmatter:

```
my-skills/
  .claude/
    skills/
      content-blog/
        SKILL.md               # skill definition (name, description, instructions)
        scripts/               # Python scripts (run via uv)
        references/            # reference docs, prompt templates
        templates/             # code generation templates
      video-editor/
        SKILL.md
        scripts/
        references/
      ...
```

The `SKILL.md` frontmatter defines the skill's name and description. Claude Code discovers these automatically when the directory is passed via `--add-dir`.

## Sync

Skills sync via the same `agentkb sync push` / `agentkb sync pull` commands as wiki and chats. The skills directory is a git repo — agentkb handles clone, commit, and push.

```bash
agentkb sync push        # push skill changes (if you edit locally)
agentkb sync pull        # pull latest skills from remote
agentkb sync status      # show all store remotes including skills
```

## Getting Started with Starter Skills

If you don't have your own skills yet, fork the public starter repo:

```bash
# Fork Isaac-Flath/agent-starter-skills on GitHub, then:
agentkb settings set skills_remote "git@github.com:youruser/agent-starter-skills.git"
agentkb sync pull
```

This gives you a working set of skills you can customize. As you develop your own, they diverge from the starter and become yours.

## What's on Disk

```
~/.agentkb/skills/              # default skills directory (or custom via skills_path)
  .claude/
    skills/
      skill-name/
        SKILL.md
        scripts/
        references/
```

No `.index/` directory — skills are not indexed. agentkb manages the git lifecycle; Claude Code consumes the files directly.
