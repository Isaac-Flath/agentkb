---
title: Hooks (Historical)
description: Historical note: the old Claude Code hooks docs no longer describe the current CLI.
order: 99
---

# Hooks (Historical)

Older versions of agentkb documentation described CLI-managed Claude Code hooks.

Those docs no longer match the current codebase.

## Current Recommendation

Instead of relying on agentkb-managed hooks, tell your agent to:

- run `agentkb status` near session start when useful
- search the wiki or chats before starting work on a topic
- use `agentkb consolidate` when you want to turn recent chat history into wiki knowledge

## Search Reminder

For conceptual knowledge:

```bash
agentkb search "query"
agentkb search -s chats "query"
```

For code in the current repo:

```bash
colgrep "query"
```
