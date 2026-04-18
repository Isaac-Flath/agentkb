---
title: Search Quality Plan — Structured Preamble + Metadata Pre-Filter
description: Plan for two search-quality changes inspired by ColGREP (structured preamble) and NextPlaid (SQL WHERE pre-filtering).
order: 99
---

# Search Quality Plan — Structured Preamble + Metadata Pre-Filter

Two changes to improve retrieval quality and query expressiveness, inspired by comparing AgentKB's current stack to Dropbox **Witchcraft** and LightOn **NextPlaid / ColGREP**. Both are additive, don't touch the wire protocol of any store, and compose: do the preamble first, then filtering, because filtering benefits from the same metadata we'll fold into the preamble.

Related context lives in the wiki: [Local Multi-Vector Search Tools](https://github.com/isaacflath/agentkb/blob/main/wiki/tools/local-multi-vector-search-tools.md).

## Current state

- Chats and wiki both build a minimal structured preamble in `_make_chat_structured_text` (`src/agentkb/chats/parser.py:479`) and `_make_structured_text` (`src/agentkb/wiki/parser.py:27`). Today that preamble is just `[collection] Title > Section` + `Tags: ...`.
- `IndexStore` (`src/agentkb/store.py`) stores documents in SQLite (`documents` + `documents_fts`) plus a PLAID index. Columns are schema-level: `collection`, `file`, `line`, `name`, `unit_type`, `content`, `raw_content`, `title`, `section`, `tags` (JSON).
- Chat session frontmatter already carries `source`, `project`, `session_id`, `date`, `messages`, `source_jsonl` — parsed in `_chat_item_from_markdown` (`src/agentkb/chats/cli.py:73`) — but that metadata is **dropped on the floor** between the session metadata parser and the chunker. The index never sees it, so neither embedding nor filtering can use it.
- Current "filters" at query time are regex on content (`-e`), path globs (`--include` / `--exclude`), and coarse scope (`-s wiki | chats | all`). There's no way to say "chats in project `raw2draft` since 2026-03-01."

So both changes are really about plumbing existing metadata to places that already exist to consume it.

---

## Plan 1 — Expand the structured preamble

**Goal.** Give the ColBERT encoder more signal per chunk by prepending a metadata block the model can attend to. ColGREP does this for code functions with `# Signature: / # Calls: / # File:`. We do the equivalent for chat chunks (date, project, source, session topic) and wiki chunks (description, heading path, URL).

### What the preamble should look like

**Chats:**

```
# Collection: chats
# Source: claude
# Project: raw2draft
# Date: 2026-04-15
# Session: Users-iflath-git-agentkb--research-pi-history
# Section: > Tool use > Parsing jsonl
# Tags: indexing, parser
# First user turn: "can you look into how pi stores its sessions"

<chunk body>
```

**Wiki:**

```
# Collection: wiki
# Title: DaVinci Resolve Scripting API
# Description: API gotchas, mediaType:1 for overlays, Fusion recipes, ...
# Section path: Transform math > Zoom/crop traps
# Tags: davinci, video-editing, api
# File: wiki/video/davinci-resolve-api.md

<chunk body>
```

Keep it short — every preamble token costs embedding budget. Aim for <150 tokens of preamble per chunk. For chats, skip `First user turn` when the chunk already begins with a user turn to avoid duplicating it.

### Why these fields

- **Source / project / date** (chats): query-time scoping words users actually type — "in raw2draft last month", "from pi sessions". Including them lexically gives ColBERT a route to match them.
- **First user turn** (chats): chat transcripts are full of tool output noise. A chunk from the middle of a 40-minute session embeds poorly because its gravity is not "what was the session about." Prepending the session's opening user turn gives every chunk a topical anchor.
- **Section path** (both): the heading trail, not just the immediate section. "Fusion > Node tree > Gotcha" tells the model more than "Gotcha."
- **Description** (wiki): the frontmatter `description:` is a human-curated summary. Already in every wiki page. Free signal.
- **Tags** (both): already included today, keep them. Normalize list formatting.

### Files to touch

- `src/agentkb/chats/parser.py:479` — extend `_make_chat_structured_text` to accept a `meta: dict` and render the block. Change `build_chat_index` (same file, ~line 596) to pass session frontmatter through.
- `src/agentkb/chats/parser.py` — in the chunker, plumb through session-level metadata (`source`, `project`, `date`, `session_id`, first user turn) alongside the current `title / section / tags`. The readable-markdown frontmatter has everything — just read it once per file and thread it into each chunk.
- `src/agentkb/wiki/parser.py:27` — extend `_make_structured_text` to take `description` (from frontmatter) and a `section_path` list.
- `src/agentkb/utils.py` — if `chunk_markdown` doesn't already return the heading trail, compute it (stack of headings at each chunk boundary). Cheap.
- Tests: extend `tests/` cases for both parsers to lock the preamble format.

### Migration

- Full reindex required on first run. Stamp an index schema version (`__preamble_version__: 2`) in `IndexStore.state.json` next to `__model__`. If the version differs, rebuild. Reuse the existing "model changed → rebuild" mechanism at `build_chat_index` (~line 518).
- Chats reindex = rebuilding ~47k chunks. On CPU with ColBERT that's 10-30 minutes depending on model. Acceptable.

### Measurement

Don't ship this by vibes. Before-and-after with a fixed query set:

1. Curate 20-30 queries with known-good target sessions/pages. Mix of topical (`"DaVinci mediaType gotcha"`), project-scoped (`"raw2draft terminal bridge"`), temporal (`"what did I decide about skills architecture"`), and chat-specific (`"the bug I fixed with the file watcher"`).
2. Build a simple script under `tests/` or `scripts/eval/` that runs each query against the current index and records MRR + Recall@5.
3. Build with the new preamble, rerun. Accept if MRR improves on the full set and doesn't regress more than 5% on any sub-slice.
4. Keep the eval set and script in the repo so future changes get scored against it.

If MRR is flat or worse, shrink the preamble — probably the `First user turn` field, which is the riskiest (token cost, may dominate short chunks).

### Risks

- **Preamble drowns short chunks.** For a 50-token chat chunk, a 150-token preamble will dominate the MaxSim signal. Consider capping preamble length proportionally to body length, or dropping fields when the body is short.
- **Leakage at query time.** ColBERT query encoding won't see the preamble — that's fine, it's asymmetric on purpose. But verify that `Encoder.encode_query` isn't accidentally prepending anything symmetric (quick check in `src/agentkb/encoder.py:61`).
- **FTS5 side effects.** The structured preamble also lands in `documents.content`, which feeds `documents_fts`. That means keyword search will start matching on field names like "Project" or "Source". Option: populate FTS from `raw_content` instead of `content`, or keep both and accept the noise.

---

## Plan 3 — Metadata pre-filtering via SQL WHERE

**Goal.** Let queries narrow the candidate set by metadata *before* PLAID scoring runs, NextPlaid-style. Today filtering is post-hoc on paths/regex; we want `--project raw2draft --since 2026-03` to cut scoring work and sharpen results.

### Schema change

Add first-class columns to the `documents` table in `IndexStore.create` (`src/agentkb/store.py`, ~line 55). New nullable columns (to keep wiki rows valid without filling them):

```sql
ALTER TABLE documents ADD COLUMN project   TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN source    TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN session_id TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN date      TEXT NOT NULL DEFAULT ''; -- ISO8601 YYYY-MM-DD
CREATE INDEX IF NOT EXISTS idx_documents_project  ON documents(project);
CREATE INDEX IF NOT EXISTS idx_documents_source   ON documents(source);
CREATE INDEX IF NOT EXISTS idx_documents_date     ON documents(date);
```

Wiki rows leave these empty. Chat rows populate them at index time. Future stores can fill whichever apply.

### Indexing change

In `build_chat_index` (`src/agentkb/chats/parser.py:491`), the loop that builds `docs` (around line 596) already has access to session metadata from the readable-markdown frontmatter. Pass the four fields into the doc dict and store.add_documents will persist them.

Update `IndexStore.add_documents` to accept and insert the new columns. One-liner in the INSERT.

### Query surface (CLI)

Two options, in order of preference:

**Option A — discrete flags (ship first):**

```bash
agentkb search -s chats --project raw2draft --since 2026-03-01 "file watcher bug"
agentkb search -s chats --source claude --until 2026-04-01 "skills refactor"
agentkb search -s all --project agentkb "search design"
```

Implementation: add Click options to the search command (`src/agentkb/cli.py` or wherever the search command lives — `search.py`/`chats/cli.py`). Each maps to a SQL predicate. AND them together. Keep `-s wiki/chats/all` as today but treat `--project` / `--source` as additional narrowing.

**Option B — generic `--filter` expression (defer):**

```bash
agentkb search --filter "project='raw2draft' AND date >= '2026-03-01'" "query"
```

Parse safely (whitelist columns and operators; never pass user input into SQL raw). Nice for power users but not needed day-one. Skip unless Option A proves too rigid.

### Pre-filter, not post-filter

The win is doing the filter *before* PLAID scoring so fewer candidates get scored. Two implementation paths:

1. **Restrict PLAID candidates.** Before calling PLAID search, run a SELECT on `documents` with the WHERE clause to get the eligible `id` set. Pass those ids to PLAID as the search scope. Check whether our PLAID wrapper supports id-restricted search — if not, fall back to (2).
2. **Score everything, filter after.** Run PLAID and FTS5 as today; intersect with the id set from a WHERE query before RRF fusion. Correct, simpler, but wastes scoring cycles on a big index.

Ship (2) first (simpler, no PLAID API digging), move to (1) if latency suffers.

### Files to touch

- `src/agentkb/store.py` — add columns, indexes, update `add_documents`; add a `filter_ids(where_clause, params) -> set[int]` helper.
- `src/agentkb/chats/parser.py` — populate new fields in the doc dict (~line 596).
- `src/agentkb/search.py` — accept filter params in the search function, intersect with PLAID/FTS results.
- `src/agentkb/cli.py` (or the search CLI module) — add `--project`, `--since`, `--until`, `--source` options. `--since` / `--until` should parse human strings via the existing `parse_time_filter` helper (already used in `chats/cli.py`).
- Docs: update `docs/search.md` with the new flags. Add one section to `docs/stores/chats.md` about metadata-scoped search.

### Migration

Same schema-version stamp as Plan 1. Reindex chats once; wiki rows just get empty strings and keep working. No disruption to existing queries — new flags are purely additive.

### Measurement

Same eval set as Plan 1. Specifically hold out ~5 queries that *should* benefit from project scoping (e.g., a query term that's ambiguous across projects) and verify MRR jumps on those with `--project` set.

---

## Order of execution

1. **Plan 1 first.** Preamble expansion is pure preprocessing: no schema change, no new CLI surface, and its benefit is measurable against today's search behavior in isolation.
2. **Eval harness next.** The queries + scoring script should land with Plan 1 so Plan 3's benefit is measurable and we don't double the migration risk.
3. **Plan 3.** Schema change + CLI flags. Ship Option A only. Leave `--filter` for later if anyone asks.
4. One reindex covers both changes — stamp `__schema_version__: 2` once and move on. Don't ship Plan 1 with one reindex and Plan 3 with another.

## Explicitly out of scope

- Single-file SQLite for everything Witchcraft-style. Tempting, but conflicts with AgentKB's markdown-first wiki contract (users edit `.md` files directly). Revisit only if we later want portable / syncable index snapshots.
- Changing the ColBERT model. Orthogonal. If we want a code-tuned model for a future code store, that's a separate decision.
- Tree-sitter code parsing. Code indexing was explicitly handed off to colgrep (`docs/index.md`, `docs/architecture.md`). Don't re-import it.

## Open questions

- Does our PLAID wrapper support id-restricted candidate sets? If yes, Plan 3 gets path (1) cheaply. If no, is it worth contributing upstream?
- Is `First user turn` actually useful, or does it just eat token budget? Eval will tell.
- Should wiki rows also carry a `project` column (mapping wiki pages to projects via frontmatter) or is that overreach? Start without it; add if users ask for project-scoped wiki search.
