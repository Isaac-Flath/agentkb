## Consolidation Report

### Paths

{paths}

### Chat Sessions

Browse the readable chat exports directory above. Sessions are named
`YYYY-MM-DD--project--slug.md`. Review sessions from the last {since}.

Use the readable exports only to identify sessions in scope and get a rough overview.
For every non-trivial session in the time range, read the corresponding raw JSONL
from start to finish before deciding what was learned. The raw JSONL is the primary
source of evidence.

Treat a session as non-trivial if it includes any of:
- debugging
- planning or design work
- multiple tool calls
- code or document edits
- user corrections
- visible iteration, retries, or course changes
- more than 10 messages

### How to Use This Report

Work through all sessions in the time range. If there's a lot, take the
time — thoroughness matters more than speed. Every session might contain
knowledge worth capturing.

Read schema.md first. The wiki is general-purpose — it makes the agent
smarter over time across all projects and domains. Everything learned goes here.

### Rules

**No fabrication.** Never infer connections or conclusions not in the source material.
If you can't point to the specific session where something was learned, don't write it.
Don't narrativize ("this proved the concept that led to X") unless someone actually said
that. Stick to what's in the sessions.

**Verify every URL.** Every URL, file path, and link must be verified by reading the
actual file or page before writing it. Don't guess slug patterns, route names, or
directory structures. Read the file system or the actual page to confirm.

**Verify existing content.** When updating existing pages, verify that existing content
is still accurate. Existing content may be wrong — previous passes may have fabricated
details, inverted values, or drawn incorrect conclusions. Check claims against the
source sessions.

**Page purpose test.** Before writing a page, state what question it answers. If the
answer is "what is this project about" or "what happened," that's not a wiki
page. It should answer "how do I do X well" or "what goes wrong when Y" or "what did
we learn about Z."

**Delete bad pages.** Review existing pages critically. Delete pages that are thin,
fabricated, stale, or redundant. A bad page is worse than no page — it wastes time
and erodes trust in the wiki.

**Do not extract by keyword hunt.** Do not mine sessions by searching for expected
terms like "Slack", "meeting", "local-only", "error", or similar and then treat those
hits as the knowledge. Search is for navigation only after you have already read the
session. The most valuable lessons are often the ones that are not announced by obvious
keywords.

### Required Working Method

Keep a session ledger while consolidating. For every session in scope, record:
- readable reviewed: yes/no
- raw reviewed: yes/no
- why it was trivial or non-trivial
- candidate lessons
- pages updated, or `no durable lesson`

Do not update the wiki until the ledger covers every session in the time range.

### What to Extract

Look for anything learned that wasn't known before:

- **Mistakes and corrections** — something was tried, it failed, a different approach
  worked. Include both the wrong and right way.
- **Technical traps** — API gotchas, silent failures, parameter quirks. Exact names,
  values, error messages.
- **Taste and judgment** — quality standards, what looks good vs. bad, and *why*.
  The reasoning matters more than the conclusion.
- **People** — who they are, how they think, how they give feedback, what they're
  good at, shared context. Helps predict and adapt.
- **Writing and communication** — principles, techniques, style preferences, influences.
- **Tools and workflows** — how to use them effectively. Gotchas, shortcuts, patterns.
- **Books and influences** — specific ideas extracted and how they're applied.
- **Domain knowledge** — anything about a field or practice that helps future work.
- **Mental models** — decision-making frameworks, principles, opinions from experience.

### How to Extract

Read each non-trivial raw session sequentially. Do not skim for topic words.

Look for **friction**, not just topics:
- something simple took surprisingly many tries
- the plan changed mid-session
- the user corrected the agent
- one approach failed and a fallback worked
- the same issue resurfaced multiple times
- a tool behaved differently than expected
- a judgment call required iteration to get right
- the final answer depended on an exact value, command, path, or error message

After each raw session, ask:
- What was harder than it should have been?
- What did we believe at first that turned out to be wrong?
- What finally unlocked progress?
- What would future-me likely get wrong again?

Prefer lessons with visible iteration, correction, surprise, or cost.
A long struggle on a small task is often more valuable than a clean success on a big one.

### Quality Bar

A thin page:
```
# Semantic Clustering
Built a pipeline using ColBERT + HDBSCAN to cluster chat sessions.
This was the precursor to agentkb.
```
This says nothing useful. What parameters worked? What failed? What would you do
differently? Delete it.

A substantial page:
```
# DaVinci Resolve Scripting API
## Timeline frame offset
When placing items on the timeline, recordFrame must include the timeline's
start offset. At 30fps with timeline starting at 01:00:00:00, the offset is
108000 frames. Forgetting the offset places items in the wrong location with
no error — it silently succeeds in the wrong place.
```
This prevents a specific mistake. It has the exact value, the exact consequence,
and the exact fix.

### Decompose into Reusable Knowledge

Split by what the knowledge is *about*, not where it was learned. Debugging CRDT sync
might produce knowledge about Go concurrency (fatal concurrent map access), SQLite
(connection starvation), and CRDTs (merge semantics) — three different pages. One
experience, multiple reusable lessons.

### For Existing Pages

Review critically. Every pass should leave pages more complete, accurate, and useful:
- **Verify existing content against source sessions** — don't trust it blindly
- Fix stale or wrong information
- Add new lessons from recent sessions
- Enrich thin sections with real depth from the raw sessions
- Restructure if the page has grown or understanding has evolved
- Delete pages that don't meet the quality bar
- Ensure References section has verified URLs to source sessions and docs
- When understanding evolves: if the opinion simply changed, update it. If the
  evolution itself is instructive (tried X, hit problem Z, switched to Y), keep
  both views — the journey is the knowledge.

### For New Topics

Only create a page with enough substance to be useful. A thin page is worse than no
page. Skip version numbers, deployment configs, and anything stale next month.

### References

Use the **local filesystem as the authority** for agentkb-managed data during consolidation.
Verify local files first, then reference them clearly:
- Local chat sessions: use local readable/session paths under `~/.agentkb/chats/` as the source of truth
- Local wiki pages: use relative links (e.g., `../tools/ffmpeg.md`)
- External resources: use verified URLs to official docs, articles, blog posts
- Remote GitHub URLs are for externally published references or explicit sync verification, not as a substitute for local verification
- Every link or path should explain why it's relevant, not just drop a bare reference

### Always

- Place pages in directories: wiki/writing/, wiki/video-editing/, wiki/tools/,
  wiki/people/, etc. Don't leave pages flat in wiki/.
- Update index.md with a one-line summary for each page
- Cross-reference between pages with relative links and [[wikilinks]]
