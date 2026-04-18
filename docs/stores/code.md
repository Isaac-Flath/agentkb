---
title: Code Store (Historical)
description: Historical note: built-in code indexing was removed from agentkb.
order: 99
---

# Code Store (Historical)

AgentKB used to include a built-in code store that parsed source files and indexed them for semantic search.

That store was **removed in April 2026**.

## Why It Was Removed

Built-in code indexing pulled agentkb toward being a code-search tool instead of a memory system. The current architecture is cleaner when:

- **agentkb** handles knowledge, chat history, sync, and consolidation
- **specialized tools** handle code search

## What To Use Instead

For code search in the current project, use **colgrep**:

```bash
colgrep "error handling logic"
colgrep -e "async fn" "retry"
```

Use normal file tools when you need direct inspection:

```bash
read path/to/file.py
```

## Current Role of AgentKB

Today agentkb focuses on:

- **Wiki** — distilled durable knowledge
- **Chats** — searchable coding-agent history
- **Skills** — repeatable workflows stored as files
