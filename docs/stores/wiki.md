---
title: Wiki
description: A wiki of plain markdown files maintained by you and your agents.
order: 2
---

# Wiki

The wiki is a directory of plain markdown files. You and your agents write them, organize them, and search them. It's a general-purpose knowledge store that makes the agent smarter over time.

This covers everything: technical gotchas, writing craft, people and relationships, tools and workflows, taste and judgment, domain expertise, mental models. If knowing it helps do better work next time, it belongs here.

The wiki complements skills rather than replacing them. Skills are procedures. The wiki is knowledge.

## Commands

```bash
agentkb store wiki init               # create a wiki at the default path
agentkb store wiki init ./my-wiki     # create a wiki at an explicit path
agentkb store wiki ingest ./notes.md  # copy a source file into the wiki
agentkb store wiki index              # build or update the search index
agentkb store wiki status             # show page and source counts
```

## How It Works

When you run `agentkb store wiki init`, agentkb creates:

```text
~/.agentkb/wiki/
  wiki/          # your pages go here
  sources/       # raw input documents
  schema.md      # writing conventions
  index.md       # page catalog
  log.md         # operation log
```

Pages are plain markdown. Frontmatter is optional. Use directories to group related pages (`wiki/tools/`, `wiki/writing/`, etc.).

## Writing Pages

The short version:

- **Capture knowledge that makes the agent more capable.**
- **Decompose project experience into reusable lessons.**
- **Lead with the answer and be specific.**
- **Record both the wrong and right approach when that matters.**
- **Keep improving pages as understanding evolves.**

Read `schema.md` before doing serious wiki work.

## Searching the Wiki

```bash
# Search wiki only
agentkb search -s wiki "why did we choose JWT"

# Search wiki + chats together
agentkb search -s all "authentication flow"
```

The wiki auto-reindexes before search if files changed.

## Where It Lives

```text
~/.agentkb/wiki/
  wiki/
  sources/
  schema.md
  index.md
  log.md
  .index/
```

agentkb also checks for in-project wiki overrides. If `.agentkb/wiki/` or `.knowledge/` exists in the current project, that path wins over the global default.

## Browsing Locally

The wiki is just markdown files. Open it in any editor or Obsidian vault.

```bash
ls ~/.agentkb/wiki/wiki/
cat ~/.agentkb/wiki/wiki/davinci-resolve.md
```

## Sync

The wiki can live in a git repo for sync across machines and agent access. The `.index/` directory is `.gitignore`d and rebuilds locally on first search.

```bash
agentkb settings set wiki_path "~/git/my-wiki"
agentkb settings set wiki_remote "git@github.com:user/my-wiki.git"
agentkb sync push
agentkb sync pull
```

See [Sync](../sync.md) for full setup.
