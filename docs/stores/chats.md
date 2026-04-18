---
title: Chat History
description: Search your coding-agent conversation history.
order: 3
---

# Chat History

The chat history store indexes your coding-agent conversations so you can search them. Every user message, assistant response, tool call, and tool result is searchable by meaning or by exact text.

Built-in sources currently include:

- **Claude Code** — `~/.claude/projects/`
- **Pi** — `~/.pi/agent/sessions/`

## Commands

```bash
agentkb store chats export                    # copy sessions from all known sources
agentkb store chats export --project air      # export only sessions matching "air"
agentkb store chats index                     # export + build search index
agentkb store chats index --project air       # index only matching sessions
agentkb store chats status                    # show session and chunk counts
```

## How It Works

Each source goes through the same three stages:

### Stage 1: Export (raw JSONL copy)

`agentkb store chats export` copies JSONL files from each registered source into agentkb-owned storage under `~/.agentkb/chats/sessions/`. Only new or changed files are copied.

### Stage 2: Readable Markdown

Each session is rendered as readable markdown in `~/.agentkb/chats/readable/`. Files are organized by month with filenames like:

```text
2026-04-16--pi--Users-iflath-git-agentkb--can-you-make-a-commit.md
2026-04-15--claude--Users-iflath-git-agentkb--research-pi-history.md
```

The readable export includes:

- user messages in full
- assistant text and thinking blocks
- tool calls formatted for readability
- tool results capped to a reasonable length
- timestamps on every message
- YAML frontmatter with session metadata and provenance

### Stage 3: Index

The readable markdown files are chunked by heading boundaries and indexed with ColBERT embeddings + FTS5. Search runs against that readable layer.

### The Full Pipeline

```text
source JSONL
  -> ~/.agentkb/chats/sessions/{source}/...
  -> ~/.agentkb/chats/readable/YYYY-MM/...
  -> ~/.agentkb/chats/.index/
```

All three stages run automatically when you search (`agentkb search -s chats`) or run `agentkb store chats index`.

## Searching Chats

```bash
# Search chat history
agentkb search -s chats "how did I fix the auth bug"

# Search wiki + chats together
agentkb search -s all "database migration"

# Regex pre-filter on chat content
agentkb search -s chats -e "error" "deployment issues"
```

## Where It Lives

```text
~/.agentkb/chats/
  sessions/
    claude/
      {project-dir}/
        {session-id}.jsonl
    pi/
      {project-dir}/
        {session-id}.jsonl
  readable/
    _index.md
    _state.json
    2026-04/
      2026-04-15--claude--project--slug.md
      2026-04-16--pi--project--slug.md
  .index/
    metadata.db
    plaid/
    state.json
```

## Browsing Locally

The readable markdown files are the easiest way to browse your history:

```bash
cat ~/.agentkb/chats/readable/_index.md
ls ~/.agentkb/chats/readable/2026-04/
```

The raw JSONL files are also available if you need them:

```bash
find ~/.agentkb/chats/sessions -name "*.jsonl" | wc -l
```

## Sync

Chat history syncs across machines via git. Both `sessions/` and `readable/` sync. The `.index/` directory is `.gitignore`d and rebuilds locally on first search.

```bash
agentkb settings set chats_path "~/git/my-chats"
agentkb settings set chats_remote "git@github.com:user/my-chats.git"
agentkb sync push
agentkb sync pull
```

See [Sync](../sync.md) for full setup.

## From Chat History to Knowledge

Chat history is the raw material. The [consolidation](../consolidation.md) command points the agent at recent sessions so it can distill durable lessons into the wiki.
