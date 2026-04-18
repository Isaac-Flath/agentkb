---
title: Architecture
description: How agentkb works internally and how to extend it.
order: 6
---

# Architecture

AgentKB is a local-first knowledge system for agents. Its current core is **persistent wiki pages + searchable coding-agent chat history**, with **skills** as a git-synced filesystem sidecar.

Built-in code indexing was removed in April 2026. Code search now belongs to specialized tools like **colgrep**.

## Purpose

- **Chat history** captures what was tried, what failed, and what was learned.
- **The wiki** captures the distilled version of those lessons so they compound over time.
- **Skills** provide repeatable procedures on disk.
- **agentkb** handles indexing, search, sync, and consolidation plumbing.

## Current Stores

| Store | Syncs? | Indexed? | Location |
|-------|--------|----------|----------|
| `wiki` | yes | yes | `~/.agentkb/wiki/` |
| `chats` | yes | yes | `~/.agentkb/chats/` |
| `skills` | yes | no | `~/.agentkb/skills/` |

## Architecture

```text
                    +---------------------------+
                    |     CLI (agentkb)         |
                    |  search | index | status  |
                    |  sync | consolidate       |
                    +------------+--------------+
                                 |
                    +------------+------------+
                    |                         |
             +------v------+          +------v------+
             |  Wiki Store |          | Chats Store |
             | markdown    |          | JSONL copy  |
             | chunking    |          | + readable  |
             | by heading  |          | rendering   |
             +------+------+          +------+------+
                    |                         |
                    +------------+------------+
                                 |
                    +------------v--------------+
                    |   Unified Search Pipeline |
                    +------------+--------------+
                                 |
                    +------------+------------+
                    |                         |
             +------v------+          +------v------+
             | PLAID Index |          | SQLite FTS5 |
             | semantic    |          | keyword     |
             +------+------+          +------+------+
                    |                         |
                    +------------+------------+
                                 |
                         +-------v-------+
                         |  RRF Fusion   |
                         +---------------+
```

## Chat Pipeline

Chat history supports multiple coding-agent sources inside one chats store.

### Raw sessions

```text
~/.agentkb/chats/sessions/
  claude/
  pi/
```

### Readable exports

```text
~/.agentkb/chats/readable/
  2026-04/
    2026-04-15--claude--Users-iflath-git-agentkb--...
    2026-04-16--pi--Users-iflath-git-agentkb--...
```

The readable markdown frontmatter includes provenance such as:

- `source`
- `source_jsonl`
- `session_id`
- `project`
- `date`
- `messages`

### Source-specific normalization

Different agent sources have different raw formats, so agentkb keeps source-specific parsing code under:

```text
src/agentkb/chats/sources/
  claude.py
  pi.py
```

Both normalize into the same readable-markdown pipeline so indexing and search stay shared.

## Search Pipeline Detail

```text
query
  -> ColBERT query encoding
  -> PLAID semantic search
  -> FTS5 keyword search
  -> RRF fusion
  -> include/exclude/regex filters
  -> formatted results
```

Important rule: **PLAID scores are not normalized across collections**. When multiple collections are searched together, agentkb merges them by rank rather than raw score.

## Indexing Pipeline

```text
source file changed?
  -> compare against state.json file hashes
  -> unchanged: skip
  -> changed: re-chunk, re-encode, update index
```

Indexes are ephemeral caches rebuilt locally on demand.

## Consolidation

```text
agentkb consolidate --since "7 days"
  -> auto-export chats from all known sources
  -> print local paths
  -> print consolidation instructions from shipped prompt
  -> agent reads sessions and updates wiki pages
```

Consolidation no longer relies on git activity. Chat history is the primary raw material; the agent does the synthesis.

## On-Disk Layout

```text
~/.agentkb/
  config.json
  wiki/
    wiki/
    sources/
    schema.md
    index.md
    .index/
  chats/
    sessions/
      claude/
      pi/
    readable/
    .index/
  skills/
    .claude/skills/
```

## Adding a New Store Type

To add a new store:

1. Create `src/agentkb/<store>/`
2. Add a `cli.py` with the store's commands
3. Add parsing / rendering / indexing code for that store
4. Register the click group in `src/agentkb/cli.py`
5. Add search-scope support in `src/agentkb/search.py` if the store is searchable
6. Add path settings in `src/agentkb/config.py` if the store has persistent on-disk data
7. Add sync integration in `src/agentkb/sync.py` if the store should be git-synced

Keep source-specific normalization in code when raw formats diverge.

## Shared Utilities

`utils.py` provides helpers that stores can reuse:

- `file_hash(path)`
- `parse_frontmatter(text)`
- `strip_frontmatter(text)`
- `chunk_markdown(path)`
- `chunk_markdown_directory(root)`

## Code Layout

```text
src/agentkb/
  cli.py
  config.py
  encoder.py
  search.py
  store.py
  sync.py
  traceability.py
  utils.py
  prompts/
  wiki/
  chats/
  skills/
```

## Design Principles

- **No LLM calls inside the library**
- **Indexes are ephemeral; sources are persistent**
- **Agents write wiki files directly using normal file tools**
- **Keep source-specific parsing in code when source formats diverge**
- **Use external tools for specialized code search**
