---
title: Implementation Roadmap: Communication and Reference Stores
description: Concrete phased roadmap for adding communications and references to agentkb.
---

# Implementation Roadmap: Communication and Reference Stores

This roadmap turns the earlier store plan into an implementation sequence that fits the **current** agentkb codebase.

## Summary recommendation

Build this in **five phases**:

1. **Phase 0 — foundation + doc alignment**
2. **Phase 1 — communications MVP** using Slack export first
3. **Phase 2 — communications expansion** for messages / social posts / meeting transcripts
4. **Phase 3 — references MVP** using existing local repos first, then git mirrors
5. **Phase 4 — hardening, consolidation, and UX polish**

If you want the fastest path to value, I would prioritize:

1. **Slack export** in `communications`
2. **watch existing local repo paths** in `references`
3. **message / social import support**
4. **git mirror support + release notes**
5. **meeting transcripts** later in `communications`

That gets useful search quickly while leaving transcript-specific work until later.

---

## Principles to keep fixed during implementation

These should be treated as guardrails, not open questions during the build:

- **Do not reintroduce the old built-in code store.**
- **Use source-specific parsers** when source formats differ.
- **Keep indexes ephemeral and source data persistent.**
- **Keep `wiki` as the distilled knowledge layer.**
- **Do not include `communications` in `all` initially.**
- **Do support syncing communications to a private remote.**
- **Do treat communications as a real feed into the wiki, with privacy-aware filtering and agent judgment.**
- **Use local repo mirrors + ColGREP for code search**, not agentkb-native source parsing.

---

## Current codebase impact

The current repo shape matters for planning:

- `src/agentkb/cli.py` hardcodes store registration and search scope handling
- `src/agentkb/search.py` hardcodes scope-to-collection mapping
- `src/agentkb/config.py` hardcodes path + remote settings
- `src/agentkb/sync.py` hardcodes which stores participate in git sync
- `src/agentkb/chats/` already contains the best template for a multi-source searchable raw-data store
- repo docs still mention the old `code` store in places, so docs need alignment as part of this work

That means the roadmap should be **incremental and explicit**, not a giant abstract plugin refactor.

---

## Phase 0 — foundation + doc alignment

### Goal

Prepare the repo so the next two stores can land cleanly without first doing a large architecture rewrite.

### Deliverables

#### 0.1 Align docs with current reality

Update docs so they describe the current product accurately before adding more store types.

Files likely touched:

- `README.md`
- `docs/index.md`
- `docs/architecture.md`
- `docs/stores/code.md` or remove/archive it
- search/scope docs that still imply code is a built-in store

This matters because otherwise the new roadmap lands on top of already-stale architecture docs.

#### 0.2 Add path/config placeholders for new stores

Extend `src/agentkb/config.py` with path settings for:

- `communications_path`
- `references_path`

Recommended defaults:

- `~/.agentkb/communications`
- `~/.agentkb/references`

Add the communications sync remote in Phase 0 as well.

Suggested initial setting behavior:

- `communications_path`: yes
- `communications_remote`: yes
- `references_path`: yes
- `references_remote`: defer until manifest-vs-mirror sync policy is implemented

#### 0.3 Decide one small internal reuse boundary

Do **not** do a broad store plugin system first.

Do extract only the pieces that are obviously reusable from `chats`:

- source registry pattern
- readable markdown rendering pattern
- incremental indexing pattern (`state.json` + file hashes)

This can be done by copying first, then extracting shared helpers only after one new store works.

### Acceptance criteria

- repo docs no longer describe a first-class built-in code store
- config can resolve communications/references directories
- communications sync settings are plumbed through the config/sync layer
- existing wiki/chats/skills behavior still works

### Estimated effort

- small

---

## Phase 1 — communications MVP

### Goal

Ship the first new searchable communications store around the message/thread model you care about most.

### Recommendation

Start with **Slack export**.

Why:

- it has the richest practical value early
- it exercises thread structure, participants, replies, and metadata
- it proves the communications architecture on real conversations rather than transcript-only files
- it aligns with the eventual social-post model better than transcripts do

### Scope of the MVP

Support importing Slack export data from a local folder into a new `communications` store.

### New package layout

```text
src/agentkb/communications/
  __init__.py
  cli.py
  parser.py
  sources/
    __init__.py
    slack.py
```

### CLI surface for MVP

```bash
agentkb store communications import slack --path ~/exports/slack
agentkb store communications index
agentkb store communications status
agentkb search -s communications "how did we describe the evaluation setup"
```

### On-disk layout for MVP

```text
~/.agentkb/communications/
  raw/
    slack/
  readable/
    2026-04/
      2026-04-16--slack--research-thread--retrieval-eval.md
  .index/
```

### Implementation tasks

#### 1.1 Add store paths and CLI registration

Files likely touched:

- `src/agentkb/config.py`
- `src/agentkb/cli.py`
- `src/agentkb/search.py`

Changes:

- add `paths.communications_dir()`
- register `communications` click group
- add `communications` search scope
- extend `_scope_to_collections()`
- update `status()` to display communications counts
- update top-level `index()` to include communications if data exists

#### 1.2 Build communications source registry

Mirror the successful `chats/sources/` pattern.

Suggested normalized event shape:

- `source`
- `kind`
- `conversation_id`
- `message_id`
- `author`
- `participants`
- `timestamp`
- `title`
- `text`
- `source_path`
- `visibility`

The readable export should still be the indexed layer.

#### 1.3 Implement Slack importer

Importer responsibilities:

- read Slack export files
- resolve users / display names where possible
- preserve channels, DMs, threads, replies, timestamps, and provenance
- write normalized raw copies into `raw/slack/`
- render readable markdown into `readable/YYYY-MM/`

Keep the parser tolerant:

- if user metadata is incomplete, still ingest messages with stable identifiers
- if thread linkage is partial, still preserve the local message order and provenance

#### 1.4 Implement readable markdown format

Readable format should bias toward human inspection and search quality.

Suggested frontmatter:

- `source: slack`
- `kind: thread` / `dm` / `channel`
- `conversation_id`
- `date`
- `participants`
- `visibility`
- `source_path`

Suggested body shape:

- title
- metadata block
- thread grouped in chronological order with reply context intact

#### 1.5 Implement indexing

Reuse the same indexing pattern as `chats`:

- compare readable file hashes to state
- re-chunk only changed files
- encode changed chunks only
- store under collection `communications`

Chunking guidance for MVP:

- chunk by markdown headings if present
- otherwise chunk transcript into moderate windows by speaker changes or line counts

### Tests to add

Suggested new tests:

- `tests/test_communications_registry.py`
- `tests/test_communications_parser.py`
- `tests/test_slack_source.py`
- search scope tests in `tests/test_search.py`
- CLI/status tests in a new communications test file

### Acceptance criteria

- Slack export data can be imported and indexed
- `agentkb search -s communications ...` returns meaningful thread-level chunks
- search JSON output remains clean
- communications is **not** included in `-s all`
- communications sync works when `communications_remote` is configured

### Estimated effort

- medium

---

## Phase 2 — communications expansion

### Goal

Add the communication sources you actually care about once the store model is proven.

### Recommended source order

1. **researcher posts / social feed imports**
2. **meeting transcripts**

### 2.1 Slack

Add:

```text
src/agentkb/communications/sources/slack.py
```

CLI:

```bash
agentkb store communications import slack --path ~/exports/slack
```

Normalization concerns:

- channels vs DMs vs threads
- users map / display names
- replies and parent messages
- attachments and links
- privacy tagging

Readable export should keep thread context together rather than indexing each isolated line.

### 2.2 Researcher posts / social

Treat these as communication, not references.

Add importers for exported or fetched post archives later, but keep the normalization compatible with the same store.

Good first cut:

- one post = one readable item
- thread replies grouped where possible
- author and URL preserved as provenance

### Privacy work for this phase

Before broadening beyond Slack, add these controls:

- `visibility` frontmatter / metadata
- include/exclude source filters on import
- allow per-source disable flags
- optional redacted readable exports later if needed

### Tests to add

- Slack thread normalization tests
- participant metadata tests
- privacy metadata tests
- reply-thread readable rendering tests

### Acceptance criteria

- Slack threads search well as coherent discussions
- private communications stay opt-in and local-first
- social posts can be searched by author/topic/source

### Estimated effort

- medium to large depending on source formats

---

## Phase 3 — references MVP

### Goal

Add a second new store for external repos/docs without rebuilding code indexing inside agentkb.

### Recommendation

Start with **watching existing local repo paths**, not cloning remotes.

Why:

- you already keep many repos locally in `~/git`
- much faster to implement
- immediately useful for things like `pi`, `pylate`, `next-plaid`
- avoids sync/mirror policy complexity in the MVP

### MVP scope

Support registering a local directory as a watched reference, extracting a readable searchable subset, and re-indexing when it changes.

### New package layout

```text
src/agentkb/references/
  __init__.py
  cli.py
  parser.py
  manifest.py
```

If needed later:

```text
src/agentkb/references/sources/
  git.py
  docs.py
```

### CLI surface for MVP

```bash
agentkb store references add local pi ~/git/pi
agentkb store references add local pylate ~/git/pylate
agentkb store references refresh
agentkb store references index
agentkb store references status
agentkb search -s references "how do pi extensions work"
```

### On-disk layout for MVP

```text
~/.agentkb/references/
  manifest.json
  readable/
    pi/
      current/
        README.md
        docs/
        CHANGELOG.md
    pylate/
      current/
        README.md
        docs/
  .index/
```

### Implementation tasks

#### 3.1 Add manifest support

The manifest should track watched references like:

- `name`
- `kind` (`local`, later `git`, later `docs`)
- `path` or `remote`
- `branch` if relevant
- `extract_paths`
- `index_mode`
- `last_refreshed`
- `last_revision`

Keep this file human-readable and easy to edit.

#### 3.2 Implement `add local`

`add local` should:

- validate path exists
- validate it is a directory
- optionally detect git revision if inside a repo
- write/update manifest entry

Suggested default extract set:

- `README*`
- `docs/**`
- `CHANGELOG*`
- `examples/**`
- maybe `prompts/**` or `specs/**` if present

Do **not** extract every source file by default.

#### 3.3 Implement `refresh`

For local-path references, `refresh` should:

- inspect the source path
- detect current git revision if available
- copy or render selected readable files into `references/readable/{name}/current/`
- save refresh metadata

A simple first version can just copy markdown/text files that match the extract patterns.

#### 3.4 Implement indexing

Use the same incremental pattern as wiki/chats:

- readable files are indexed
- only changed readable files re-encode
- collection name is `references`

Suggested structured text for embeddings:

- reference name
- source path / repo name
- section title
- relative file path
- extracted content

#### 3.5 Add search scope and status

Files likely touched:

- `src/agentkb/cli.py`
- `src/agentkb/search.py`
- `src/agentkb/config.py`

Behavior:

- `agentkb search -s references ...`
- top-level `status` shows watched reference count + indexed chunk count
- top-level `index` includes references if present

### Tests to add

Suggested new tests:

- `tests/test_references_manifest.py`
- `tests/test_references_parser.py`
- `tests/test_references_cli.py`
- search scope tests
- refresh behavior tests with tmp git repos

### Acceptance criteria

- existing local repos can be added as references
- README/docs/changelogs become searchable through `references`
- implementation detail can still be followed up with ColGREP in the original repo
- no full-source-file indexing is introduced

### Estimated effort

- medium

---

## Phase 4 — references expansion + hardening

### Goal

Make references truly useful for keeping external knowledge current.

### 4.1 Add git mirror mode

After `local` works, add:

```bash
agentkb store references add git pi git@github.com:mariozechner/pi.git --branch main
```

This should maintain a local mirror or working clone under:

```text
~/.agentkb/references/mirrors/pi/
```

Then the readable extraction pipeline runs from the mirror.

### 4.2 Add release notes / issues / PR extracts

Useful next layers:

- GitHub releases
- selected issues or PRs
- changelog diffs since last refresh

These should still land in the `references` readable layer, not in the wiki.

### 4.3 Add change reporting

Useful commands later:

```bash
agentkb store references refresh --since-last
agentkb store references changes pi
```

This should answer:

- what changed upstream since last time?
- which docs/release notes were added?
- which readable files were re-indexed?

### 4.4 Decide sync strategy

Recommended default:

- sync `manifest.json`
- do **not** sync large mirrors by default
- optionally sync small readable extracts later if they prove valuable

This is intentionally different from communications.

### Acceptance criteria

- mirrors can be refreshed incrementally
- large repos do not bloat normal sync flows
- references stay reproducible from upstream

### Estimated effort

- medium

---

## Phase 5 — consolidation + UX polish

### Goal

Make the new stores useful without making them noisy or unsafe.

### 5.1 Selective consolidation

Add new prompts only after the raw stores are working.

Suggested prompts:

- `consolidate_communications`
- `consolidate_references`

Default behavior should stay deliberate:

- communications: included as a consolidation feed into the wiki, but never blindly distilled
- references: selective extraction of stable tool/domain knowledge into wiki

### 5.2 Cross-store UX decisions

Decide later, not now:

- whether `all` should ever include communications
- whether references belongs in `all`
- whether to add a broader `memory` scope

My recommendation:

- keep `communications` out of `all`
- references could eventually join `all`, but only after relevance/noise looks good

### 5.3 Quality-of-life commands

Potential later commands:

```bash
agentkb store communications list-sources
agentkb store communications re-render
agentkb store references list
agentkb store references refresh pi
agentkb store references remove pylate
```

### 5.4 Hardening

Before calling this done, make sure:

- JSON output stays clean under all new commands
- state files survive partial refresh failures
- readable filenames stay stable
- provenance is always preserved back to source path or URL

---

## Suggested order of concrete PRs

If I were implementing this in the repo right now, I would break it into PRs like this:

### PR 1 — doc alignment + path plumbing

- update stale docs
- add `communications_path`, `communications_remote`, and `references_path`
- keep behavior changes limited to config/sync plumbing

### PR 2 — communications skeleton

- add `src/agentkb/communications/`
- register CLI group
- add empty `status` / `index` plumbing
- add tests for scope registration

### PR 3 — Slack MVP

- `import slack`
- raw + readable + index pipeline
- search scope support
- docs/tests

### PR 4 — references skeleton + manifest

- add `src/agentkb/references/`
- manifest support
- CLI registration
- status/index plumbing

### PR 5 — references local-path MVP

- `references add local`
- `refresh`
- readable extraction
- index/search/docs/tests

### PR 6 — social importers

- social / researcher-post importer
- privacy metadata

### PR 7 — git mirror mode for references

- `add git`
- mirror refresh
- revision tracking

### PR 8 — meeting transcripts + consolidation polish

- `import meeting`
- transcript rendering
- consolidation prompts and UX refinements

This sequence keeps each PR understandable and testable.

---

## Recommended “not yet” list

These are tempting, but I would explicitly defer them:

- a generic plugin architecture for all stores
- automatic ingestion from live Slack/Twitter APIs
- broad automatic redistillation of communications into wiki without review
- including communications in `all`
- indexing every file in watched repos
- agentkb-native semantic code search for watched repos
- fully automated consolidation from private communication into wiki

Deferring these keeps the architecture clean.

---

## Minimum viable end state

If you stopped after the most valuable MVPs, I think the best stopping point would be:

### Communications

- Slack export import
- message / social imports
- private git-synced searchable readable store
- explicit `-s communications`
- communications available as a consolidation feed into the wiki

### References

- watch existing local repos
- extract README/docs/changelog/examples
- explicit `-s references`
- follow implementation details in the repo with ColGREP

### Wiki

- still the place for distilled durable takeaways

That would already cover the two use cases you described without making agentkb overly complex.

---

## My recommendation on sequencing for your setup

Because you already have a strong local repo workflow and want message-like communications first, I would build in this order:

1. **communications: Slack**
2. **references: local repo watcher**
3. **communications: social posts**
4. **references: git mirrors + releases**
5. **communications: meeting transcripts**

That order gives you useful personal memory and useful external-tool memory quickly, while postponing the most privacy-sensitive and parser-heavy sources until the architecture is proven.
