---
title: Plan: Communication and Reference Stores
description: Proposed store strategy for human communication data and continuously updated external repositories/docs.
---

# Plan: Communication and Reference Stores

## Goal

Add support for two new classes of material in agentkb:

1. **Human communication**
   - Slack threads
   - meeting transcripts
   - posts from researchers / people you follow
2. **Continuously updated external knowledge sources**
   - watched repos like `pylate`, `next-plaid`, `pi`
   - documentation trees
   - changelogs / release notes / selected issues or PRs

## Baseline assumptions

This plan assumes the newer agentkb direction:

- **wiki** is the distilled long-term knowledge store
- **chats** is the raw searchable interaction log
- **skills** are procedures, not indexed knowledge
- **indexes are ephemeral; source data is persistent**
- **source-specific parsers belong in code when source formats differ**
- **specialized code search should stay outside agentkb** (for example ColGREP), rather than reintroducing a full built-in code store

That baseline matters for the second category: repos should not automatically imply “bring back code indexing inside agentkb.”

## Recommendation

Do **not** put both categories into one generic catch-all store.

They have very different lifecycles:

- communication is usually **append-heavy**, thread-oriented, identity-heavy, and privacy-sensitive
- watched repos/docs are **mutable snapshots**, refresh from upstream, and often need code search outside agentkb

Instead, add **two new stores**:

1. **`communications` store** — searchable raw communication and transcript data
2. **`references` store** — tracked external repos/docs with refresh + optional searchable text extraction

The **wiki** remains where durable lessons get distilled.

---

## Store 1: `communications`

### What belongs here

Anything that is fundamentally “messages or spoken interaction involving people”:

- Slack DMs and channels
- meeting transcripts
- interview transcripts
- Twitter / X posts, Mastodon posts, Bluesky posts, newsletters, or feed items from people you track
- potentially email later

A useful mental model:

- **direct conversation** → DM / thread / transcript
- **broadcast communication** → post / article / talk transcript
- both still belong in a people-centered communication store

### Why this should be separate from `chats`

The current `chats` store already has a good pipeline:

- raw source files
- source-specific normalization
- readable markdown export
- semantic + keyword index

That architecture should be reused.

But human communication has different needs than coding-agent chats:

- participant metadata matters a lot
- privacy rules are stricter
- thread structure matters more than tool calls
- consolidation into wiki should be much more conservative

So I would **not** overload `chats` directly at first.

I would add a sibling store now, then decide later whether `chats` and `communications` should merge under a broader “conversations” umbrella.

### Proposed on-disk layout

```text
~/.agentkb/communications/
  raw/
    slack/
    meetings/
    twitter/
  readable/
    2026-04/
      2026-04-16--slack--team-thread--launch-plan.md
      2026-04-16--meeting--research-sync--speaker-review.md
      2026-04-16--twitter--author-handle--post-slug.md
  .index/
```

### Normalized record shape

Each importer should normalize source data into a shared event model with fields like:

- `source` — slack, meeting, twitter, etc.
- `kind` — dm, group_thread, meeting, post, reply
- `conversation_id` / `thread_id`
- `message_id`
- `parent_id` (for replies)
- `author`
- `participants`
- `timestamp`
- `title`
- `text`
- `attachments`
- `visibility` — private, shared, public
- `source_path` or `source_url`
- `import_hash`

The readable markdown export can still be the indexed layer, just like `chats`.

### Chunking strategy

Do **not** chunk only by individual message.

Better defaults:

- Slack / text threads: chunk by thread windows or heading breaks
- meeting transcripts: chunk by speaker/topic sections
- social posts: one post + reply context per chunk or per small thread

Search results need enough local context to make a message meaningful.

### Search behavior

Add a dedicated scope:

```bash
agentkb search -s communications "what did Ben say about late interaction indexing"
```

I would **not** include communications in `-s all` initially.

Reason:

- it is noisy
- it is highly personal
- it changes the privacy expectations of a broad search

If later desired, add a broader scope like `-s memory` or an explicit `-s all-private`.

### Sync and privacy

This is the most important design point.

Suggested defaults:

- **local-first**
- **git-synced to a private remote**
- keep communications in a **private repo distinct from public repos**

Good follow-up features:

- per-source enable/disable
- per-source sync policy
- optional redacted readable export
- tag-based exclusion (for example family, medical, legal, private)
- opt-out folders or people lists

### Consolidation behavior

Communications should be a **real feed into the wiki**, not a dead-end archive.

A good default would be:

- searchable as raw communication memory
- included in consolidation workflows that feed the wiki
- handled with privacy-aware filtering and explicit agent judgment
- perhaps via a separate prompt like `consolidate_communications`

That keeps the wiki high-signal without turning private conversation into overconfident “facts.”

### Example CLI surface

```bash
agentkb store communications import slack --path ~/exports/slack
agentkb store communications import meeting --path ~/notes/transcripts/
agentkb store communications index
agentkb store communications status
agentkb search -s communications "how did we describe the evaluation setup"
```

---

## Store 2: `references`

### What belongs here

Anything that is fundamentally “an external thing I want kept current”:

- git repos you want locally mirrored or refreshed
- docs trees you want to search
- changelogs and release notes
- selected issues / PRs that matter
- examples / notebooks / guides from upstream projects

Your examples fit well:

- `pi`
- `pylate`
- `next-plaid`
- other projects agentkb depends on or builds on

### Core principle

This store should **not** bring back agentkb’s old built-in code index.

Instead:

- agentkb manages the **watch list**, **refresh**, **provenance**, and optionally **text extraction**
- when you need actual code search, use **ColGREP / normal file tools** in the mirrored repo

That matches the current architecture direction much better.

### Proposed on-disk layout

```text
~/.agentkb/references/
  manifest.json
  mirrors/
    pi/
    pylate/
    next-plaid/
  readable/
    pi/
      current/
        README.md
        docs/
        CHANGELOG.md
        releases/
    pylate/
      current/
        README.md
        docs/
        examples/
  .index/
```

### Manifest model

Track each watched source with metadata like:

- `name`
- `kind` — git_repo, github_repo, docs_site
- `remote`
- `branch`
- `local_path`
- `refresh_policy` — manual, daily, weekly, on-search
- `extract_paths` — README, docs/**, CHANGELOG*, examples/**
- `index_mode` — docs_only, docs_and_examples, metadata_only
- `last_refreshed`
- `last_indexed_revision`

This manifest is the real source of truth for what to keep current.

### Refresh model

For git-backed sources:

- clone if missing
- fetch/pull on refresh
- detect current commit hash
- only re-extract / re-index changed files

For docs-only sources:

- fetch to a local snapshot directory
- hash files / responses
- regenerate readable extracts incrementally

### What gets indexed

I would start by indexing only the **human-readable text layer**, for example:

- README
- docs markdown
- changelogs
- release notes
- examples / tutorials
- carefully selected issues / PRs

I would **not** start by indexing every source file.

That keeps the store aligned with agentkb’s strengths:

- semantic search over text knowledge
- preserved provenance
- light incremental updates

### When code search is needed

If a result points into a mirrored repo and you need implementation detail:

1. open the local mirror
2. use `colgrep`
3. read files directly

That gives you the best of both systems:

- agentkb remembers the ecosystem and keeps it current
- specialized tools handle code search well

### Sync policy

Unlike communications, I would **not** sync repo mirrors by default through agentkb.

Why:

- mirrors can be large
- they are reproducible from upstream
- syncing clones is usually wasteful

Better split:

- sync the **manifest**
- optionally sync small **derived readable extracts** if useful
- rehydrate mirrors from origin on each machine

### Search behavior

Add a dedicated scope:

```bash
agentkb search -s references "how does pi define extensions"
```

This scope should work well for:

- “what changed in this dependency?”
- “where are the relevant docs for this thing?”
- “what do release notes say about this API?”

### Consolidation behavior

This store should feed the wiki selectively.

Examples:

- new pylate indexing constraint → add/update a wiki page on pylate / ColBERT behavior
- pi API change → update a wiki page on pi extension architecture
- next-plaid gotcha → add a tool-specific knowledge note

The raw mirrored docs stay in `references`; the distilled operational knowledge goes to `wiki`.

### Example CLI surface

```bash
agentkb store references add git pi git@github.com:mariozechner/pi.git --branch main
agentkb store references add git pylate git@github.com:lightonai/pylate.git
agentkb store references add docs next-plaid https://...
agentkb store references refresh
agentkb store references index
agentkb store references status
agentkb search -s references "late interaction reranking"
```

---

## Why not one store for both?

A single “sources” store sounds simpler, but it would mix together things with very different rules:

| Concern | Communications | References |
|---|---|---|
| Lifecycle | append-only / thread growth | mutable snapshot / upstream refresh |
| Privacy | high | usually low |
| Primary unit | message / thread / transcript | repo / doc / release |
| Sync default | local-only or private | manifest-only, rehydrate mirrors |
| Consolidation | conservative | tool/docs knowledge extraction |
| Code search | usually irrelevant | often needed, but should use external tools |

That difference is large enough that two stores are cleaner.

---

## Relationship to existing stores

### `wiki`

Still the destination for durable, reusable knowledge.

- people knowledge
- tool gotchas
- architecture lessons
- summaries of repeated themes from meetings or research posts

### `chats`

Keep `chats` for coding-agent session history for now.

Longer term, there are two viable paths:

1. leave `chats` as agent-only, `communications` as human-only
2. unify both under a broader `conversations` umbrella

I would start with **separate stores**, because it keeps privacy, UX, and migration simpler.

### `skills`

Skills remain the right place for repeatable workflows:

- how to import Slack
- how to refresh watched repos
- how to run consolidation on new references

But the data itself should not live in skills.

---

## Suggested implementation order

### Phase 1: `communications`

Start here if the goal is personal memory and relationship context.

Recommended first importers:

1. Slack export
2. researcher posts / social archives
3. meeting transcripts

Why this order:

- Slack gives the richest practical value earliest
- researcher posts fit the same store and are useful for idea capture
- meeting transcripts are still valuable, but they can come later after the core message/thread model is working

Deliverables:

- new store path + config
- source registry
- normalized message model
- readable export
- search scope
- strict privacy defaults

### Phase 2: `references`

Start here if the goal is “keep important upstream systems current.”

Recommended first source types:

1. local git mirrors of watched repos
2. extraction of README / docs / changelog
3. release note capture

Deliverables:

- manifest
- refresh command
- docs extraction pipeline
- search scope
- incremental re-index by revision hash

### Phase 3: consolidation and cross-store UX

After both stores exist:

- add consolidation prompts that treat communications as a wiki feed
- decide whether `all` should include either of them
- add explicit commands for “what changed since last refresh?”
- maybe add a higher-level `memory` scope later

---

## My concrete recommendation for your examples

### Put these in `communications`

- Slack messages
- meeting transcripts
- Twitter / X posts from researchers you track

For posts, model them as **broadcast communication** rather than as repo references.

### Put these in `references`

- `pi`
- `pylate`
- `next-plaid`
- other upstream repos or docs you want kept current

Track them as **watched references with local mirrors + indexed readable docs**, not as a rebuilt built-in code store.

### Put distilled takeaways in `wiki`

Examples:

- “Ben’s preferred evaluation framing for retrieval experiments”
- “Pi extension API gotchas”
- “Pylate / PLAID constraints around indexing and scoring”

### Put procedures in `skills`

Examples:

- import a Slack export
- refresh all watched references
- extract release notes
- run a consolidation pass

---

## Open questions to decide before implementation

1. Should `communications` be searchable only by explicit scope, or included in `all`?
2. What privacy / redaction rules should communications sync use by default?
3. For `references`, do you care more about:
   - docs/searchability, or
   - true code search across mirrors?
4. Should repo mirrors live under `~/.agentkb/references/mirrors/`, or should agentkb also support “watch an existing local path” like `~/git/pi`?
5. Do you want public social feeds mixed into communications, or split later into a separate `feeds` subtype?

## Bottom line

If I were implementing this now, I would:

1. add **`communications`** for private/human message-like data, synced to a private repo and used as a wiki feed
2. add **`references`** for watched external repos/docs
3. keep **`wiki`** as the distilled knowledge layer
4. keep **code search outside agentkb** and use local mirrors + ColGREP when implementation detail matters

That gives you a cleaner architecture than a single mixed store, and it matches the current agentkb direction much better.
