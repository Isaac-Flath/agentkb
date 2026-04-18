"""Wiki manager: initialization, ingestion, and status."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_SCHEMA = """\
# Wiki

A general-purpose wiki that makes the agent smarter over time. Everything
learned from any conversation, any project, any domain goes here. This is not tied to
one project — it's accumulated knowledge that helps do everything better.

## What This Is

Every time you work on something and learn something you didn't know before, it belongs
here. The goal: the agent gets smarter with each session, carrying forward knowledge
across all projects and domains.

This covers everything: technical knowledge, writing craft, people and relationships,
tools and workflows, taste and judgment, mental models, domain expertise. If knowing it
would help you do better work next time — in any context — it belongs here.

**The test for every sentence: would this prevent a mistake, save time, improve quality,
or change a decision if you read it six months from now?** If not, it doesn't belong.

## What Belongs Here

Knowledge that makes the agent more capable. Not project status — capability.

- **Mistakes and corrections**: what was tried, why it failed, what actually worked.
  Include the wrong approach so you recognize it next time.
- **API gotchas and technical traps**: undocumented behavior, silent failures, parameter
  quirks. Exact function names, exact values, exact error messages.
- **Techniques that worked vs. didn't**: specific approaches with enough detail to
  reproduce or avoid. Not "clustering worked" but the parameters, the failures, the
  iteration that got to the working version.
- **Taste and judgment**: decisions where docs don't help. Quality standards. What looks
  good vs. bad. Why — not just what was chosen but the reasoning. "Mobile-first overlays
  because 70% of YouTube views are on phones and text under 52px is unreadable at
  6 inches."
- **People**: who they are, how they think, what they're good at, how to work with them,
  what kind of feedback they give, shared context. Knowing this helps predict and adapt.
- **Writing and communication**: principles, techniques, what the user values in prose,
  how they want things said, influences and how they're applied.
- **Tools and workflows**: not what the tool is, but how to use it effectively. The
  shortcuts, the gotchas, the workflows that save time.
- **Books, resources, influences**: not reviews. The specific ideas extracted and how
  they're applied in practice.
- **Mental models and frameworks**: decision-making approaches, principles that guide
  work, opinions developed through experience.
- **Domain knowledge**: anything learned about a field, industry, technology, or practice
  that would help with future work in that area.

### Decompose Project Experience into Reusable Knowledge

When you learn something while working on a specific project, ask: is this knowledge
about the project, or about something more general?

Example: debugging CRDT sync revealed that Go's concurrent map access is a fatal error
(not a data race — the runtime kills the process). That's Go concurrency knowledge, not
CRDT knowledge. It belongs on a Go concurrency page, not buried in a CRDT project page.

Split by what the knowledge is *about*, not where you happened to learn it:
- SQLite connection starvation under goroutines → Go concurrency or SQLite page
- CRDT-specific behaviors (vector clocks, merge semantics) → CRDT page
- A specific library's API quirks → page about that library
- Optimistic updates must flow through all data layers → general architecture pattern

One experience often produces knowledge for 2-3 different pages. That's good — it means
the knowledge is reusable, which is the whole point.

## Rules

**No fabrication.** Never infer connections or conclusions not in the source material.
If you can't point to the specific session where something was learned, don't write it.
Don't narrativize ("this proved the concept that led to X") unless someone actually said
that.

**Verify every URL and path.** Every URL, file path, and link must be verified by
reading the actual file or page before writing it. Don't guess slug patterns, route
names, or directory structures.

**Page purpose test.** Before writing a page, state what question it answers. Good:
"how do I avoid DaVinci Resolve's silent mediaType failures." Bad: "what is this project
about." If a page answers "what happened" instead of "what was learned," it doesn't
belong.

**Delete bad pages.** A thin, fabricated, stale, or redundant page is worse than no
page. Delete them.

## What Does NOT Belong

- **Version numbers, exact configs, deployment details** — stale immediately. Belongs
  with the code.
- **News or status updates** — "shipped X" or "project is in Y state." That's a commit
  message.
- **High-level summaries without substance** — "built a clustering pipeline" tells
  future-you nothing useful. What worked? What didn't? What would you do differently?
- **Anything derivable from code or git history** — don't duplicate `git log`.
- **Fabricated narratives** — don't connect dots that aren't connected in the source
  material. "This was the precursor to X" is a claim that needs evidence.

## How to Write a Page

### Lead with the answer (Cornell method, Wikipedia lead section)

The first 2-3 sentences of every page should be a self-contained summary. If your future
self reads only those sentences, they should get 80% of the value. Then elaborate.

### Write each page assuming total context loss (Knuth, Matuschak)

Write as if the reader has seen nothing else in this wiki. Include enough
context that the page is self-contained: what problem this solves, what domain it belongs
to, what the key terms mean. If the reader needs to read three other pages first to
understand this one, the page has failed.

### Headings should describe content, not categories

"How Pan interacts with Zoom in undocumented ways" beats "Pan and Zoom." Headings are
the API of the page — they should tell you whether to keep reading.

### Be specific

Bad: "The coordinate system was confusing and took a while to figure out."

Good: "Pan/Tilt values are in pixels relative to center of project resolution. Pan
positive = right. ZoomX interacts with Pan in undocumented ways — the math that should
work doesn't. When overlays get cut off, set Pan=0 and iterate rather than computing
from first principles."

### Always include the "why" (Knuth)

Don't just record what works — record why. Why this approach over another? Why does the
API behave this way? Why was this taste decision made? The reasoning is often more
valuable than the conclusion, because it lets you adapt when circumstances change.

### Write in your own words (Luhmann, Ahrens)

Never copy-paste from docs or transcripts. If you can't restate it, you don't understand
it well enough to teach it to your future self. Restatement creates knowledge; copy-paste
creates the illusion of knowledge.

### Tone

Write flat and factual. State what works and what doesn't. No "interestingly" or
"it should be noted." Specific examples and exact values over adjectives.

### Depth over breadth

A page with 3 vague sentences is worse than no page — delete it. Don't create a page
until you have enough to say something real. When you do, make it worth reading.

To get depth, read the raw JSONL chat sessions (not just the readable markdown
summaries). The summaries give you the topic; the raw sessions have the actual
debugging loops, error messages, failed approaches, and corrections.

### Quality bar

Thin (delete this):
```
# Semantic Clustering
Built a pipeline using ColBERT + HDBSCAN to cluster chat sessions.
This was the precursor to agentkb.
```
Says nothing useful. No parameters, no failures, no lessons. And "precursor to agentkb"
is a fabricated narrative — nobody said that in any session.

Substantial (keep this):
```
# DaVinci Resolve: timeline frame offset
When placing items on the timeline, recordFrame must include the timeline's
start offset. At 30fps with timeline starting at 01:00:00:00, the offset is
108000 frames. Forgetting the offset places items in the wrong location with
no error — it silently succeeds in the wrong place.

I wasted an hour on this because SetProperty returns True even when the item
is placed off-screen.
```
Prevents a specific mistake. Exact value, exact consequence, exact trap.

## Page Granularity

Use judgment, not formulas. The unit of a page is the unit of retrieval — what would
someone search for?

- If a topic is tight and fits in a few paragraphs, it's one page. Don't split.
- If a page grows large and sections serve different retrieval needs (someone might
  want "Go channel patterns" without reading about "Go map concurrency"), split it.
- If a directory accumulates many pages on related subtopics, that's fine — it means
  the knowledge is rich.

Wikipedia's test: if a section could stand alone as a complete article that someone
would search for independently, it should be its own page.

## References and Links

### Link to sources with URLs wherever possible

Every page should end with a `## References` section containing:
- URLs to chat sessions in the chat history repo (GitHub raw URLs preferred)
- URLs to official docs, articles, blog posts, or repos
- Relative links to related wiki pages: `See [ffmpeg text rendering](../tools/ffmpeg.md)
  for the drawtext escaping rules used here.`

### Every link should explain why it's relevant (Luhmann)

Don't drop bare links. Write one sentence explaining the relationship: "See [[Go
concurrency]] for the mutex patterns discovered while debugging this." The link text
and context should tell the reader whether following it is worth their time.

## Updating Existing Pages

When you touch a page, verify first, then improve. Existing content may be wrong —
previous passes may have fabricated details, inverted values, or drawn incorrect
conclusions. Check claims against the source sessions before building on them.

Fix stale information. Add new lessons. Remove anything wrong. Delete pages that don't
meet the quality bar. A page should reflect current best understanding, not a historical
snapshot.

When understanding evolves, use judgment: if an opinion simply changed (you now prefer
tool X over tool Y), update to the current view. If the evolution itself is instructive
(you thought X was better until you hit problem Z, then switched to Y), keep both the
old view and the new one — the journey is the knowledge.

## Structure

Pages live in `wiki/` and must be placed in a subdirectory by topic area. Don't leave
pages flat in `wiki/`. Standard directories:

- `wiki/writing/` — writing craft, style, rhetoric, editing
- `wiki/video-editing/` — DaVinci Resolve, ffmpeg, video production
- `wiki/tools/` — software tools, APIs, workflows
- `wiki/people/` — individuals, working relationships, feedback styles
- `wiki/architecture/` — software design patterns, system design lessons

Create new directories as needed. The directory name should describe the knowledge domain.

Raw source documents live in `sources/`. Cross-reference between pages with
relative links (`../tools/ffmpeg.md`) and [[Page Title]] wikilinks.

Prefer flat linking over deep hierarchy. Pages should be findable by search and by
following links from related pages.

## Index

Keep `index.md` as a short, scannable catalog. One line per page with a description
that tells you whether to read it. Group by directory. The index should give enough
context that an agent can decide "I should read that page" without searching.
"""

DEFAULT_INDEX = """\
# Index

What's in this wiki. One line per page — enough to know whether to read it.

<!-- Group by directory. Example:
## Video Editing
- [DaVinci Resolve API](wiki/video-editing/davinci-resolve-api.md) — frame offsets, Pan/Zoom gotchas, silent mediaType failures
-->
"""

DEFAULT_LOG = """\
# Log

<!-- ## [YYYY-MM-DD] what happened -->
"""


class KnowledgeBase:
    """A wiki rooted at a directory."""

    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def init(path: Path):
        """Initialize a new wiki at the given path."""
        if (path / "schema.md").exists():
            raise FileExistsError(f"Wiki already exists at {path}")

        (path / "wiki").mkdir(parents=True, exist_ok=True)
        (path / "sources").mkdir(parents=True, exist_ok=True)

        (path / "schema.md").write_text(DEFAULT_SCHEMA)
        (path / "index.md").write_text(DEFAULT_INDEX)
        (path / "log.md").write_text(DEFAULT_LOG)

    def ingest(self, source: str) -> Path:
        """Copy a local source file into the wiki's sources/ directory."""
        source_path = Path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        dest = self.root / "sources" / source_path.name
        shutil.copy2(source_path, dest)
        self._log_ingest(source_path.name)
        return dest

    def _log_ingest(self, description: str):
        """Append an ingest entry to log.md."""
        today = datetime.now().strftime("%Y-%m-%d")
        entry = f"\n## [{today}] ingest | {description}\n\nIngested source file.\n"
        log_path = self.root / "log.md"
        with open(log_path, "a") as f:
            f.write(entry)

    def status(self) -> dict:
        """Get wiki status summary."""
        wiki_pages = self._count_md_files(self.root / "wiki")
        sources = self._count_md_files(self.root / "sources")

        return {
            "wiki_pages": wiki_pages,
            "sources": sources,
        }

    @staticmethod
    def _count_md_files(dir_path: Path) -> int:
        if not dir_path.exists():
            return 0
        return sum(1 for f in dir_path.rglob("*.md") if f.is_file())
