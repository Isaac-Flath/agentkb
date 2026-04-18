---
title: Getting Started
description: Install agentkb and run your first searches.
order: 1
---

# Getting Started

agentkb is a local-first knowledge tool for agents. It currently works across your **wiki**, **coding-agent chat history**, and **skills**. It uses ColBERT embeddings for semantic search and BM25 for keyword search, fused together so you can find things by meaning and by exact text.

> For code search in the current project, use **colgrep**. Built-in code indexing is no longer part of agentkb.

## Install

```bash
uv tool install agentkb
```

## Initialize Your Wiki

```bash
agentkb store wiki init
```

This creates:

```text
~/.agentkb/wiki/
  wiki/
  sources/
  schema.md
  index.md
  log.md
```

## Index Chat History

```bash
agentkb store chats index
```

This exports sessions from supported sources (currently Claude Code and Pi), renders readable markdown, and builds the chat index.

## Search

```bash
# Semantic search (default scope: wiki)
agentkb search "DaVinci Resolve scripting gotchas"

# Search chat history
agentkb search -s chats "how did I fix the auth bug"

# Search wiki + chats together
agentkb search -s all "authentication flow"

# Regex pre-filter + semantic ranking
agentkb search -e "error" "deployment issues"

# JSON output for scripts/agents
agentkb search --json "retry logic"
```

The first search takes longer because the model loads and indexes may rebuild. After that, searches are fast.

## Add Skills

```bash
agentkb settings set skills_remote "git@github.com:youruser/my-skills.git"
agentkb sync pull
agentkb store skills list
```

## Turn Activity into Knowledge

After working for a while, run consolidation to find what should be written down:

```bash
agentkb consolidate
agentkb consolidate --since "30 days"
```

This exports recent chat history, shows the relevant local paths, and prints consolidation instructions for the agent to follow.

## What's Next

- [Wiki](stores/wiki.md): how the wiki works, writing conventions, how agents use it
- [Chat History](stores/chats.md): searching your coding-agent conversation history
- [Consolidation](consolidation.md): turn chat history into wiki knowledge
- [Skills](stores/skills.md): agent skills managed by git
- [Search](search.md): all search flags, scopes, and filtering options
- [Sync](sync.md): back up your data and move between machines
- [Architecture](architecture.md): how the current stores work internally
