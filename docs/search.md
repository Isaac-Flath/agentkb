---
title: Search
description: All search flags, scopes, and filtering options.
order: 2
---

# Search

agentkb search combines semantic search (finds things by meaning) with keyword search (finds exact matches), fused together with reciprocal rank fusion. Semantic ranking is weighted 3x higher than keyword ranking.

> Search covers the indexed agentkb stores: **wiki** and **chats**. For code search in the current project, use **colgrep**.

## Basic Usage

```bash
# Just type a query: searches wiki by default
agentkb search "database connection pooling"

# Or use the shorthand (omit "search")
agentkb "retry logic with backoff"
```

## Scopes

| Flag | What It Searches |
|------|------------------|
| `-s wiki` (default) | Wiki pages + ingested wiki sources |
| `-s chats` | Coding-agent chat history |
| `-s all` | Wiki + chats |

```bash
agentkb search -s wiki "why did we choose JWT"
agentkb search -s chats "how did I fix the auth bug"
agentkb search -s all "authentication flow"
```

Results are tagged with their source: `[wiki]`, `[wiki:source]`, or `[chats]`.

## Filtering

### Regex Pre-Filter (`-e`)

Narrow results to documents matching a regex:

```bash
agentkb search -e "error" "deployment issues"
agentkb search -e "DaVinci" "video editing"
```

### Fixed String (`-F`)

Treat the pattern as a literal string, not regex:

```bash
agentkb search -F "TODO:" "incomplete work"
```

### Word Boundary (`-w`)

Match whole words only:

```bash
agentkb search -w -e "test" "testing patterns"
```

### File Glob (`--include`, `--exclude`)

Filter by file path patterns:

```bash
agentkb search --include="*.md" "writing style"
agentkb search --exclude="archive/*" "authentication"
```

### Exclude Directories (`--exclude-dir`)

```bash
agentkb search --exclude-dir=archive "config"
```

## Output Options

| Flag | Effect |
|------|--------|
| `-k N` | Return top N results (default: 15) |
| `-n N` | Context lines per result (default: 6) |
| `-l` | List files only, no content |
| `-c` | Full content output |
| `--json` | JSON output for scripts and agents |
| `--semantic-only` | Skip keyword search, use semantic results only |

```bash
# Top 5 results with full content
agentkb search -k 5 -c "main entry point"

# Just file paths
agentkb search -l "authentication"

# JSON for programmatic use
agentkb search --json "error handling"
```

## How Scoring Works

Each result displays its semantic score from PLAID / ColBERT search. Higher is more relevant within that search. Scores are not normalized across collections, so agentkb uses rank fusion when merging results from multiple stores.
