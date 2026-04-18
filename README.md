# AgentKB

> **Pre-alpha.** This is under active development. APIs, CLI commands, and storage formats may change without notice.

A local-first knowledge system for agents. Today its core is **persistent wiki pages + searchable agent chat history**, with **skills** as a git-synced filesystem sidecar.

The power is in the intersection:

- **Wiki** captures distilled, durable knowledge
- **Chat history** captures what was tried, what failed, and what was learned
- **Skills** capture repeatable procedures

Your data stays local in universal formats: markdown, JSONL, and normal files on disk. Indexes are ephemeral caches rebuilt from source data.

> Built-in code indexing was removed in April 2026. For code search in the current project, use **colgrep** or normal file tools.

## Install

Install as a uv tool so `agentkb` is available globally:

```bash
uv tool install agentkb
```

Or install from source for development:

```bash
uv tool install --editable --python 3.13 ~/path/to/agentkb
```

To upgrade:

```bash
uv tool upgrade agentkb
```

## Quick Start

```bash
# Initialize your wiki
agentkb store wiki init

# Export + index coding-agent chat history (Claude Code + Pi)
agentkb store chats index

# Search the wiki (default scope)
agentkb search "DaVinci Resolve scripting gotchas"

# Search chat history
agentkb search -s chats "how did I fix the auth bug"

# Search wiki + chats together
agentkb search -s all "authentication"

# Check what exists
agentkb status
```

For code search inside the current repo:

```bash
colgrep "error handling logic"
```

## Stores

AgentKB currently has three store types:

- **Wiki**: plain markdown pages you and your agents write. Hard-won lessons, techniques, taste, people, tools, domain knowledge.
- **Chat History**: coding-agent conversations exported as readable markdown, fully searchable. Built-in sources currently include Claude Code and Pi.
- **Skills**: agent skill directories (`SKILL.md` + scripts + references) managed by git. Not indexed or searched.

## Search

```bash
agentkb search "retry logic with backoff"              # semantic search (default: wiki)
agentkb search -s wiki "why did we choose JWT"         # search wiki
agentkb search -s chats "how did I fix the auth bug"   # search chat history
agentkb search -s all "authentication"                 # search wiki + chats
agentkb search -e "error" "deployment issues"         # regex + semantic
agentkb search --json "query"                          # JSON output for scripts
```

## Consolidation

Turn recent chat activity into wiki knowledge:

```bash
agentkb consolidate
agentkb consolidate --since "30 days"
```

This exports recent chat history, prints the relevant local paths, and prints consolidation instructions the agent can act on. The agent reads the sessions, extracts reusable lessons, and writes or updates wiki pages.

## Skills

Manage agent skills with git sync:

```bash
agentkb settings set skills_remote "git@github.com:user/my-skills.git"
agentkb sync pull
agentkb store skills list
```

## Sync

Back up your wiki, chat history, and skills to git remotes:

```bash
agentkb settings set wiki_remote "git@github.com:user/agentkb-wiki.git"
agentkb settings set chats_remote "git@github.com:user/agentkb-chats.git"
agentkb settings set skills_remote "git@github.com:user/my-skills.git"

agentkb sync push
agentkb sync pull
agentkb sync status
```

## Documentation

Full docs at [isaacflath.com/agentkb](https://isaacflath.com/agentkb).

## How It Works

Hybrid search: ColBERT multi-vector embeddings (semantic) + SQLite FTS5 (keyword), fused with reciprocal rank fusion. Indexes are incremental: only changed files are re-encoded.
