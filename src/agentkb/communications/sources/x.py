"""X (formerly Twitter) source — fetch and render posts from a curated handle list.

Auth: app-only bearer token via X_BEARER_TOKEN env var.
Endpoints used:
  - GET /2/users/by/username/{username}   (resolve handle → id, per-handle one-time)
  - GET /2/users/{id}/tweets              (user timeline, since_id cursor)

The /2/users/{id}/following endpoint requires OAuth 2.0 user context, not
app-only, so we manage handles explicitly via `agentkb communications x add-handle`
rather than auto-syncing the follow list.

Filtering: we skip retweets and replies-to-other-users. Originals, self-reply
threads, and quote-tweets are kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentkb.communications.sources import CommunicationSource, register


X_API_BASE = "https://api.x.com/2"
USER_AGENT = "agentkb/0.3"
MAX_TWEETS_PER_FETCH = 100  # X API cap per request
INITIAL_FETCH_PAGES = 5  # up to 500 tweets on first fetch per handle
INITIAL_FETCH_LOOKBACK_DAYS = 180  # don't go further back than this on first fetch

TWEET_FIELDS = "created_at,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,entities,public_metrics,lang"
USER_FIELDS = "username,name,description"
EXPANSIONS = "referenced_tweets.id,referenced_tweets.id.author_id,author_id"


# --- Bearer token + HTTP ---


def _bearer_token() -> str:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "X_BEARER_TOKEN is not set. Export it from your X developer portal "
            "(e.g. `source ~/.secrets`) and try again."
        )
    return token


def _api_get(path: str, params: dict | None = None) -> dict:
    """GET https://api.x.com/2{path} with bearer auth. Returns parsed JSON.

    Raises RuntimeError on HTTP error with status + body for debugging.
    Handles 429 with a single retry after the x-rate-limit-reset header.
    """
    url = X_API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_bearer_token()}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            reset = e.headers.get("x-rate-limit-reset")
            wait = max(1, int(reset) - int(time.time())) if reset else 15
            if wait <= 60:
                time.sleep(wait)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"X API {e.code} for {path}: {body}") from e


# --- Handles manifest ---


def _handles_path(raw_dir: Path) -> Path:
    return raw_dir / "_handles.json"


def load_handles(raw_dir: Path) -> dict:
    """Load the handles manifest. Returns {} if missing."""
    p = _handles_path(raw_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("handles", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_handles(raw_dir: Path, handles: dict) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    _handles_path(raw_dir).write_text(json.dumps({"handles": handles}, indent=2) + "\n")


def resolve_handle(username: str) -> dict:
    """Look up a handle's user ID + metadata via the X API."""
    username = username.lstrip("@").strip()
    data = _api_get(f"/users/by/username/{username}", {"user.fields": USER_FIELDS})
    user = data.get("data")
    if not user:
        errs = data.get("errors", [])
        raise RuntimeError(f"Could not resolve @{username}: {errs or 'not found'}")
    return user


def add_handle(raw_dir: Path, username: str) -> dict:
    """Add a handle to the manifest. Resolves via API and stores user_id."""
    username = username.lstrip("@").strip()
    handles = load_handles(raw_dir)
    if username in handles:
        return handles[username]

    user = resolve_handle(username)
    entry = {
        "user_id": user["id"],
        "name": user.get("name", ""),
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    handles[username] = entry
    save_handles(raw_dir, handles)

    # Also cache the user record for rendering.
    handle_dir = raw_dir / username
    handle_dir.mkdir(parents=True, exist_ok=True)
    (handle_dir / "user.json").write_text(json.dumps(user, indent=2) + "\n")

    return entry


def remove_handle(raw_dir: Path, username: str) -> bool:
    username = username.lstrip("@").strip()
    handles = load_handles(raw_dir)
    if username not in handles:
        return False
    del handles[username]
    save_handles(raw_dir, handles)
    return True


# --- Tweet fetch + storage ---


def _cursor_path(handle_dir: Path) -> Path:
    return handle_dir / "_cursor.json"


def _load_cursor(handle_dir: Path) -> dict:
    p = _cursor_path(handle_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cursor(handle_dir: Path, cursor: dict) -> None:
    _cursor_path(handle_dir).write_text(json.dumps(cursor, indent=2) + "\n")


def _tweet_is_kept(tweet: dict, author_id: str) -> bool:
    """Apply filter rules: skip retweets and replies-to-others.

    Keeps originals, self-reply threads, and quote-tweets.
    """
    refs = tweet.get("referenced_tweets") or []
    for ref in refs:
        if ref.get("type") == "retweeted":
            return False
    in_reply_to = tweet.get("in_reply_to_user_id")
    if in_reply_to and in_reply_to != author_id:
        return False
    return True


def _append_tweets_to_monthly(handle_dir: Path, tweets: list[dict]) -> None:
    """Append tweets to raw/x/{handle}/tweets-YYYY-MM.jsonl, grouped by month."""
    if not tweets:
        return
    by_month: dict[str, list[dict]] = {}
    for t in tweets:
        created = t.get("created_at", "")
        month = created[:7] if len(created) >= 7 else "unknown"
        by_month.setdefault(month, []).append(t)

    for month, items in by_month.items():
        path = handle_dir / f"tweets-{month}.jsonl"
        with path.open("a") as f:
            for t in items:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")


def fetch_handle_tweets(raw_dir: Path, username: str, *, max_pages: int | None = None) -> dict:
    """Fetch new tweets for one handle. Incremental via since_id cursor.

    Returns stats: {"handle": str, "fetched": int, "kept": int}.
    """
    handles = load_handles(raw_dir)
    entry = handles.get(username)
    if not entry:
        raise RuntimeError(f"Handle @{username} is not registered. Run `agentkb communications x add-handle {username}` first.")
    user_id = entry["user_id"]
    handle_dir = raw_dir / username
    handle_dir.mkdir(parents=True, exist_ok=True)

    cursor = _load_cursor(handle_dir)
    since_id = cursor.get("since_id")

    if max_pages is None:
        max_pages = 1 if since_id else INITIAL_FETCH_PAGES

    # Bound initial fetch to last N days (since_id overrides this on incremental fetches).
    start_time = None
    if not since_id:
        cutoff = datetime.now(timezone.utc) - timedelta(days=INITIAL_FETCH_LOOKBACK_DAYS)
        start_time = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    all_tweets: list[dict] = []
    all_includes_users: list[dict] = []
    all_includes_tweets: list[dict] = []
    next_token: str | None = None
    highest_id = since_id

    for _ in range(max_pages):
        params = {
            "max_results": MAX_TWEETS_PER_FETCH,
            "tweet.fields": TWEET_FIELDS,
            "user.fields": USER_FIELDS,
            "expansions": EXPANSIONS,
        }
        if since_id:
            params["since_id"] = since_id
        elif start_time:
            params["start_time"] = start_time
        if next_token:
            params["pagination_token"] = next_token

        data = _api_get(f"/users/{user_id}/tweets", params)
        tweets = data.get("data") or []
        all_tweets.extend(tweets)

        includes = data.get("includes") or {}
        all_includes_users.extend(includes.get("users") or [])
        all_includes_tweets.extend(includes.get("tweets") or [])

        for t in tweets:
            tid = t.get("id", "")
            if tid and (highest_id is None or int(tid) > int(highest_id)):
                highest_id = tid

        meta = data.get("meta") or {}
        next_token = meta.get("next_token")
        if not next_token:
            break

    kept = [t for t in all_tweets if _tweet_is_kept(t, user_id)]
    _append_tweets_to_monthly(handle_dir, kept)

    # Store referenced-tweet includes so render can resolve quote-tweets.
    if all_includes_tweets:
        includes_path = handle_dir / "_includes_tweets.jsonl"
        seen_ids = set()
        if includes_path.exists():
            for line in includes_path.read_text().splitlines():
                try:
                    seen_ids.add(json.loads(line).get("id"))
                except json.JSONDecodeError:
                    pass
        with includes_path.open("a") as f:
            for inc in all_includes_tweets:
                if inc.get("id") not in seen_ids:
                    f.write(json.dumps(inc, ensure_ascii=False) + "\n")
                    seen_ids.add(inc.get("id"))
    if all_includes_users:
        users_path = handle_dir / "_includes_users.jsonl"
        seen_ids = set()
        if users_path.exists():
            for line in users_path.read_text().splitlines():
                try:
                    seen_ids.add(json.loads(line).get("id"))
                except json.JSONDecodeError:
                    pass
        with users_path.open("a") as f:
            for inc in all_includes_users:
                if inc.get("id") not in seen_ids:
                    f.write(json.dumps(inc, ensure_ascii=False) + "\n")
                    seen_ids.add(inc.get("id"))

    cursor["since_id"] = highest_id or since_id
    cursor["last_fetched"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save_cursor(handle_dir, cursor)

    return {"handle": username, "fetched": len(all_tweets), "kept": len(kept)}


def fetch(raw_dir: Path) -> dict:
    """Fetch new tweets for every registered handle."""
    handles = load_handles(raw_dir)
    if not handles:
        return {"handles": 0, "fetched": 0, "kept": 0, "errors": []}

    total_fetched = 0
    total_kept = 0
    errors: list[str] = []
    for username in sorted(handles):
        try:
            stats = fetch_handle_tweets(raw_dir, username)
            total_fetched += stats["fetched"]
            total_kept += stats["kept"]
        except Exception as e:
            errors.append(f"{username}: {e}")
            print(f"[agentkb] X fetch failed for @{username}: {e}", file=sys.stderr)

    return {
        "handles": len(handles),
        "fetched": total_fetched,
        "kept": total_kept,
        "errors": errors,
    }


# --- Rendering: raw tweets → readable markdown ---


def _slugify(text: str, max_len: int = 60) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"https?://\S+", "", slug)
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def _expand_urls(text: str, entities: dict | None) -> str:
    """Rewrite t.co short URLs to display_url or expanded_url for readability."""
    if not entities or not text:
        return text
    urls = entities.get("urls") or []
    for u in urls:
        short = u.get("url")
        expanded = u.get("expanded_url") or u.get("display_url")
        if short and expanded:
            text = text.replace(short, expanded)
    return text


def _load_handle_tweets(handle_dir: Path) -> list[dict]:
    """Load all stored tweets for one handle, sorted by created_at ascending."""
    tweets: list[dict] = []
    for jsonl in sorted(handle_dir.glob("tweets-*.jsonl")):
        for line in jsonl.read_text().splitlines():
            try:
                tweets.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    tweets.sort(key=lambda t: (t.get("created_at", ""), t.get("id", "")))
    return tweets


def _load_includes(handle_dir: Path, kind: str) -> dict[str, dict]:
    """Load cached referenced tweets or users into an id→record map."""
    path = handle_dir / f"_includes_{kind}.jsonl"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = rec.get("id")
        if rid:
            out[rid] = rec
    return out


def _group_threads(tweets: list[dict]) -> list[list[dict]]:
    """Group tweets into threads by conversation_id, preserving chronological order."""
    by_conv: dict[str, list[dict]] = {}
    for t in tweets:
        cid = t.get("conversation_id") or t.get("id")
        by_conv.setdefault(cid, []).append(t)

    threads = list(by_conv.values())
    for thread in threads:
        thread.sort(key=lambda t: (t.get("created_at", ""), t.get("id", "")))
    threads.sort(key=lambda thread: thread[0].get("created_at", ""))
    return threads


def _render_thread(
    thread: list[dict],
    handle: str,
    user_name: str,
    includes_tweets: dict[str, dict],
    includes_users: dict[str, dict],
) -> tuple[str, dict] | None:
    """Render one thread (≥1 tweets) as markdown. Returns (content, metadata) or None."""
    if not thread:
        return None

    head = thread[0]
    head_id = head.get("id", "")
    conv_id = head.get("conversation_id") or head_id
    created = head.get("created_at", "")
    date = created[:10] if created else ""
    head_text = _expand_urls(head.get("text", ""), head.get("entities"))

    kind = "thread" if len(thread) > 1 else "tweet"
    url = f"https://x.com/{handle}/status/{head_id}" if head_id else ""

    first_line = next((l.strip() for l in head_text.splitlines() if l.strip()), "untitled")
    title = first_line[:100]

    # YAML-escape the title since it can contain colons, quotes, etc.
    safe_title = json.dumps(title, ensure_ascii=False)

    # Frontmatter
    lines = [
        "---",
        f"title: {safe_title}",
        "source: x",
        f"kind: {kind}",
        f"handle: {handle}",
        f"tweet_id: '{head_id}'",
        f"conversation_id: '{conv_id}'",
        f"date: {date}",
        f"url: {url}",
        f"length: {len(thread)}",
        "---",
        "",
        f"# {title}",
        "",
        f"**@{handle}** ({user_name})  ",
        f"**Date:** {date}  ",
        f"**URL:** {url}  ",
        f"**Length:** {len(thread)} tweet(s)",
        "",
        "---",
        "",
    ]

    for i, t in enumerate(thread):
        ts = t.get("created_at", "")
        tid = t.get("id", "")
        text = _expand_urls(t.get("text", ""), t.get("entities"))
        header = f"**{ts}**" if ts else f"**tweet {i+1}**"
        if tid:
            header += f"  ·  https://x.com/{handle}/status/{tid}"
        lines.append(header)
        lines.append("")
        lines.append(text)
        lines.append("")

        # Inline quoted tweet
        for ref in t.get("referenced_tweets") or []:
            if ref.get("type") == "quoted":
                quoted = includes_tweets.get(ref.get("id", ""))
                if quoted:
                    q_author_id = quoted.get("author_id", "")
                    q_user = includes_users.get(q_author_id) or {}
                    q_handle = q_user.get("username", "?")
                    q_text = _expand_urls(quoted.get("text", ""), quoted.get("entities"))
                    quote_block = "\n".join("> " + ln for ln in q_text.splitlines())
                    lines.append(f"> Quoting **@{q_handle}**:")
                    lines.append(quote_block)
                    lines.append("")

        if i < len(thread) - 1:
            lines.append("---")
            lines.append("")

    metadata = {
        "handle": handle,
        "kind": kind,
        "tweet_id": head_id,
        "conversation_id": conv_id,
        "date": date,
        "url": url,
        "length": len(thread),
        "title": title,
    }
    return "\n".join(lines), metadata


def render(raw_dir: Path, readable_dir: Path) -> dict:
    """Render all stored X data to readable markdown.

    Produces one markdown file per thread at
    readable/YYYY-MM/YYYY-MM-DD--x--{handle}--{slug}.md.
    """
    handles = load_handles(raw_dir)
    if not handles:
        return {"generated": 0, "skipped": 0, "total": 0}

    readable_dir.mkdir(parents=True, exist_ok=True)

    state_path = readable_dir / "_state.json"
    old_state: dict = {}
    if state_path.exists():
        try:
            old_state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    new_state: dict = {}
    generated = 0
    skipped = 0
    total = 0

    all_meta: list[dict] = []

    for handle in sorted(handles):
        handle_dir = raw_dir / handle
        if not handle_dir.exists():
            continue

        user_rec = {}
        user_file = handle_dir / "user.json"
        if user_file.exists():
            try:
                user_rec = json.loads(user_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        user_name = user_rec.get("name") or handle

        tweets = _load_handle_tweets(handle_dir)
        total += len(tweets)
        if not tweets:
            continue

        includes_tweets = _load_includes(handle_dir, "tweets")
        includes_users = _load_includes(handle_dir, "users")

        threads = _group_threads(tweets)
        for thread in threads:
            result = _render_thread(thread, handle, user_name, includes_tweets, includes_users)
            if not result:
                continue
            content, meta = result

            head_id = meta["tweet_id"]
            date = meta["date"] or "unknown"
            month = date[:7] if len(date) >= 7 else "unknown"
            slug = _slugify(meta["title"])
            filename = f"{date}--x--{handle}--{slug}--{head_id[-6:] if head_id else 'unknown'}.md"

            rel_path = f"{month}/{filename}"
            state_key = f"{handle}/{head_id}/{len(thread)}"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

            if old_state.get(state_key) == content_hash:
                new_state[state_key] = content_hash
                # Record metadata even when skipping so index.md is complete.
                meta["filename"] = rel_path
                all_meta.append(meta)
                skipped += 1
                continue

            out_path = readable_dir / month / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content)

            new_state[state_key] = content_hash
            meta["filename"] = rel_path
            all_meta.append(meta)
            generated += 1

    # Write _index.md
    all_meta.sort(key=lambda m: m.get("date", ""), reverse=True)
    index_lines = ["# Communications — X", ""]
    current_month = ""
    for m in all_meta:
        date = m.get("date", "")
        month = date[:7] if len(date) >= 7 else "unknown"
        if month != current_month:
            current_month = month
            index_lines.append(f"## {month}")
            index_lines.append("")
        fname = m.get("filename", "")
        title = m.get("title", "untitled")
        handle = m.get("handle", "")
        length = m.get("length", 1)
        suffix = f" (thread, {length})" if length > 1 else ""
        index_lines.append(f"- [{title}]({fname}) — @{handle}{suffix}")
    index_lines.append("")
    (readable_dir / "_index.md").write_text("\n".join(index_lines))

    state_path.write_text(json.dumps(new_state, indent=2) + "\n")

    return {"generated": generated, "skipped": skipped, "total": total}


register(CommunicationSource(name="x", fetch=fetch, render=render))
