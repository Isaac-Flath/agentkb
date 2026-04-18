## Consolidation Report — Communications

### Paths

{paths}

### What This Store Contains

`communications` is imported short-form content (X posts, threads, and over
time messages and transcripts). Right now it is primarily X/Twitter.

Readable threads are at:
  `~/.agentkb/communications/readable/YYYY-MM/YYYY-MM-DD--x--{{handle}}--{{slug}}--{{id}}.md`

Raw tweets (JSONL) are at:
  `~/.agentkb/communications/raw/x/{{handle}}/tweets-YYYY-MM.jsonl`

The handles manifest at `raw/x/_handles.json` lists every tracked account.

Review items from the last {since}. The tracked handles were chosen
deliberately — each one is a trust-weighted signal source for the user.

### How This Consolidation Differs from Chats

Chats are long debugging loops with corrections and taste decisions — the
signal is "what was tried, what failed, what worked." X posts are short
claims, announcements, recommendations, and paper links — the signal is
"what is worth acting on or remembering."

Most posts are noise (hot takes, restatements, culture war). A few are gold
(new technique worked, paper dropped, tool shipped, clear result). The job
is ruthless filtering.

### Focus Areas (user's interests)

Weight these topics heavily when deciding what to distill:

- **Late interaction / multi-vector retrieval** — ColBERT, PLAID, any new
  multi-vector approaches, sparse-dense hybrids, reranker work, evaluation
  methodology
- **pylate** — releases, features, benchmarks, issues, usage patterns
- **mixedbread** — releases, models, embeddings work, benchmarks,
  announcements from `@mixedbreadai`, `@bclavie`, `@antoine_chaffin`
- **LightOn** — RAG work, retrieval-augmented systems, announcements
  from `@LightOnIO`
- **Retrieval broadly** — new benchmarks, new results, failure modes,
  counterintuitive findings

Other substantive areas worth capturing when they appear:

- ColBERT.ai / DSPy / GEPA work from `@lateinteraction`
- Training / architecture findings from `@karpathy` (nanochat, LLM training)
- Tools/workflows that the user would actually adopt
- Writing / teaching / communication craft when substantive

### Linked Papers and References

**This is the highest-value case.** When a tracked author links a paper or
technical reference:

1. Follow the URL — fetch the paper (arXiv, blog post, GitHub README, docs).
2. Read the abstract, introduction, and conclusion at minimum. For claimed
   results, read the results section too.
3. Write a dedicated wiki page under `wiki/research/papers/` or
   `wiki/research/retrieval/` summarizing:
   - The claim or result (in one sentence)
   - The setup (what datasets, models, baselines)
   - Why it matters (what problem it moves on, what it supersedes)
   - Caveats (what it doesn't show, what the authors admit)
   - Citation: author, title, venue/year, URL
   - Who surfaced it (which tracked handle + tweet URL)
4. Cross-reference from the relevant topic page (e.g., a new
   late-interaction technique goes on both `wiki/research/papers/{{slug}}.md`
   and `wiki/research/retrieval/late-interaction.md`).

If a paper is only name-dropped without substantive discussion, record the
reference on the topic page but don't fabricate a summary — fetch it or skip
it. Do not guess.

### Rules

**No fabrication.** Never infer a claim, number, or result from a tweet
alone. If a tweet says "we beat X by 3 points" without numbers, and you
can't find the underlying post/paper, don't write "improves X by 3 points"
in the wiki — write "claimed improvement over X, source not yet read" and
move on.

**Attribute every claim.** Every wiki entry derived from communications
must cite the source: `[@handle tweet](url)` at minimum. The wiki is
tracking trust-weighted signals, not facts in the abstract.

**Verify every URL.** Every link must be verified by fetching it before
you rely on its content. t.co short links were already expanded during
rendering — the URLs you see are real destinations.

**Skip dead posts.** Retweets and replies to other people are already
filtered out upstream. What remains is originals, self-reply threads, and
quote-tweets. Most of those are still not wiki-worthy. A post that's a
joke, a meme, a subtweet, or a restatement of known work goes nowhere.

**Don't blindly distill.** Communications is a signal feed, not a truth
source. The wiki records what the user should *remember* or *act on*.
Most posts don't clear that bar.

**Page purpose test.** Before writing a page, state what question it
answers. If the answer is "what did @karpathy say yesterday," that's not
a wiki page. It should answer "how do X well," "what goes wrong with Y,"
"what is the current state of Z," or "what does paper X claim."

### What to Extract

From each substantive post or thread, look for:

- **New retrieval approaches** — a technique, loss function, architecture,
  training recipe, or evaluation methodology. Capture it on the appropriate
  topic page with attribution and link.
- **Concrete results** — benchmark numbers, ablations, comparisons.
  Record the exact numbers and the setup. If results are claimed but not
  backed by a post/paper, note the claim and skip.
- **Tool releases / updates** — a new version, feature, or capability of
  something the user uses or might use. Record version, date, and one-line
  summary on the tool's page.
- **Papers and references** — see the paper handling section above.
- **Domain takes with substance** — opinions backed by experience and
  concrete examples, not hot takes.
- **People context** — if a tracked author reveals how they work, what
  they care about, who they collaborate with — add to or create their
  `wiki/people/{{handle}}.md`.

### What NOT to Extract

- Hot takes, culture war, platform drama
- Restatements of things already in the wiki
- Announcements without substance ("exciting things coming")
- Screenshots, memes, jokes
- Generic motivation / career advice
- Claims without verifiable backing (paper, repo, or post you can read)

### Quality Bar

A thin entry (**delete or don't write**):
```
## ColBERT
@lateinteraction tweeted about ColBERT on 2026-03-15.
He is excited about late interaction.
```
This says nothing reusable.

A substantial entry:
```
## PyLate v1.4 — Dense+Sparse Hybrid Training

Claim: joint dense + sparse training improves BEIR average by ~1.2 pts
over dense-only at equal parameter count. Setup: ModernBERT-base, MS MARCO
train, BEIR eval, released 2026-03 in pylate v1.4. Source: @antoine_chaffin
thread https://x.com/antoine_chaffin/status/... , pylate release notes
https://github.com/lightonai/pylate/releases/tag/v1.4

Implication: when evaluating retrievers going forward, report both dense-
only and joint-trained variants — the gap matters on out-of-domain tasks
(BEIR) but is small on in-domain (MS MARCO).
```
This has the claim, the setup, the source, and the implication for future
work. Worth keeping.

### Decompose into Reusable Knowledge

One thread can produce multiple wiki entries. A thread announcing a new
multi-vector retrieval technique with a paper link might produce:
- `wiki/research/papers/{{paper-slug}}.md` — the paper summary
- `wiki/research/retrieval/late-interaction.md` — updated with the new
  technique's place in the landscape
- `wiki/people/{{handle}}.md` — updated with what the author is working on now
- `wiki/tools/pylate.md` — if the technique was released in pylate

One post, multiple reusable pages. Decompose by topic.

### For Existing Pages

Review critically. Every pass should leave pages more complete, accurate,
and useful:

- Verify existing claims against their cited source tweets/papers
- Fix stale or wrong information
- Add new findings from recent posts
- Enrich thin sections with actual paper content where links were followed
- Delete pages that don't meet the quality bar

### References

Use the **local filesystem as the authority** for agentkb-managed data.

- Local readable threads under `~/.agentkb/communications/readable/` are the
  primary source — read them, not the tweet page, whenever possible
- Raw JSONL under `~/.agentkb/communications/raw/x/{{handle}}/` is available
  if you need the full unformatted record
- Tweet URLs (`https://x.com/{{handle}}/status/{{id}}`) are for attribution and
  for anyone following a wiki page back to the original post
- Paper URLs (arXiv, GitHub, docs) must be fetched — don't cite a paper you
  haven't read

### Always

- Place pages in directories: `wiki/research/retrieval/`,
  `wiki/research/papers/`, `wiki/tools/`, `wiki/people/`, etc. Don't leave
  pages flat in `wiki/`.
- Update `index.md` with a one-line summary for each new page
- Cross-reference between pages with relative links and `[[wikilinks]]`
- Every communications-derived claim in the wiki cites the tweet URL +
  @handle that surfaced it
