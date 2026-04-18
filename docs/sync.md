---
title: Sync
description: Sync your wiki, chat history, and skills across machines using git.
order: 5
---

# Sync

agentkb uses git to sync your wiki, chat history, and skills across machines. Each synced store is its own git repo, so you get version history, diffs, and conflict resolution.

The source data syncs. The search indexes do **not**.

## What Syncs

| Data | Syncs? | How |
|------|--------|-----|
| Wiki pages + sources | Yes | Git repo (`wiki_remote`) |
| Chat sessions (JSONL) | Yes | Git repo (`chats_remote`) |
| Chat readable exports (markdown) | Yes | Git repo (`chats_remote`) |
| Skills | Yes | Git repo (`skills_remote`) |
| Wiki `.index/` | No | Rebuilt locally |
| Chat `.index/` | No | Rebuilt locally |

## Setup

### Wiki

```bash
# 1. Create a repo for your wiki
# 2. Tell agentkb where it lives
agentkb settings set wiki_path "~/git/my-wiki"
agentkb settings set wiki_remote "git@github.com:youruser/my-wiki.git"

# 3. Initialize the wiki structure
agentkb store wiki init
```

### Chat History

```bash
agentkb settings set chats_path "~/git/my-chats"
agentkb settings set chats_remote "git@github.com:youruser/my-chats.git"
```

### Skills

```bash
agentkb settings set skills_path "~/git/my-skills"
agentkb settings set skills_remote "git@github.com:youruser/my-skills.git"
agentkb sync pull
```

## Push and Pull

```bash
agentkb sync push
agentkb sync pull
agentkb sync push --dry-run
agentkb sync pull --dry-run
```

## New Machine Setup

```bash
uv tool install agentkb

agentkb settings set wiki_remote "git@github.com:youruser/my-wiki.git"
agentkb settings set wiki_path "~/git/my-wiki"
agentkb settings set chats_remote "git@github.com:youruser/my-chats.git"
agentkb settings set chats_path "~/git/my-chats"
agentkb settings set skills_remote "git@github.com:youruser/my-skills.git"
agentkb settings set skills_path "~/git/my-skills"

agentkb sync pull
```

Indexes rebuild automatically on first search.

## Check Configuration

```bash
agentkb sync status
```

This shows configured remotes, local paths, and whether each local store is a git repo.
