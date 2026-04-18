---
title: Agentkb
description: A local-first knowledge tool for agents.
order: 0
---

# Agentkb

agentkb makes agents smarter over time by braiding together three core stores:

- a **wiki** of markdown knowledge pages
- **coding-agent chat history** rendered to readable markdown
- **skills** stored as normal files on disk

The power is in the cross-intersection. Chat history captures what was tried, what failed, and what was learned. The wiki captures the distilled version so those lessons compound. Skills provide repeatable workflows.

Indexes are ephemeral caches rebuilt locally. Your source data stays in normal files you control.

> Built-in code indexing was removed. For code search in the current project, use **colgrep** or normal file tools.

## Stores

agentkb currently has three store types:

- **[Wiki](stores/wiki.md)**: plain markdown files you and your agents write. Hard-won lessons, techniques, taste, people, domain expertise.
- **[Chat History](stores/chats.md)**: coding-agent conversations from Claude Code and Pi, exported to readable markdown and indexed for search.
- **[Skills](stores/skills.md)**: agent skill directories (`SKILL.md` + scripts + references) managed by git. Not indexed or searched.

## Docs

- [Getting Started](getting-started.md): install and first search
- [Search](search.md): all flags, scopes, and filtering
- [Wiki](stores/wiki.md): the wiki, writing conventions, how agents use it
- [Chat History](stores/chats.md): exporting, indexing, what's on disk
- [Consolidation](consolidation.md): turn chat history into wiki knowledge
- [Skills](stores/skills.md): agent skills managed by git, loaded from disk
- [Sync](sync.md): back up and move between machines
- [Architecture](architecture.md): how it works internally and how to extend it
- [Code Store (historical)](stores/code.md): why built-in code indexing was removed
- [Hooks (historical)](hooks.md): note on removed hook integration docs
