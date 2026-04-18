"""Tests for the X source — handles manifest, tweet filtering, rendering.

No network: all tests use pre-built tweet fixtures.
"""

import json

from agentkb.communications.sources import x as x_source
from agentkb.communications.sources.x import (
    _expand_urls,
    _group_threads,
    _render_thread,
    _slugify,
    _tweet_is_kept,
    add_handle,
    load_handles,
    remove_handle,
    render,
    save_handles,
)


# --- Filter logic ---

AUTHOR_ID = "123"


def test_keep_original_tweet():
    """A plain tweet with no refs and no in_reply_to is kept."""
    t = {"id": "1", "author_id": AUTHOR_ID, "text": "hello"}
    assert _tweet_is_kept(t, AUTHOR_ID) is True


def test_skip_retweet():
    """Retweets (referenced_tweets with type=retweeted) are dropped."""
    t = {
        "id": "1", "author_id": AUTHOR_ID, "text": "RT ...",
        "referenced_tweets": [{"type": "retweeted", "id": "999"}],
    }
    assert _tweet_is_kept(t, AUTHOR_ID) is False


def test_skip_reply_to_other():
    """Replies to another user are dropped."""
    t = {
        "id": "1", "author_id": AUTHOR_ID, "text": "@alice nice",
        "in_reply_to_user_id": "999",
    }
    assert _tweet_is_kept(t, AUTHOR_ID) is False


def test_keep_self_reply():
    """Self-replies (thread continuations) are kept."""
    t = {
        "id": "2", "author_id": AUTHOR_ID, "text": "part 2",
        "in_reply_to_user_id": AUTHOR_ID,
        "referenced_tweets": [{"type": "replied_to", "id": "1"}],
    }
    assert _tweet_is_kept(t, AUTHOR_ID) is True


def test_keep_quote_tweet():
    """Quote-tweets are kept."""
    t = {
        "id": "1", "author_id": AUTHOR_ID, "text": "agree",
        "referenced_tweets": [{"type": "quoted", "id": "999"}],
    }
    assert _tweet_is_kept(t, AUTHOR_ID) is True


# --- Thread grouping ---


def test_group_threads_by_conversation():
    """Tweets with the same conversation_id form one thread, sorted chronologically."""
    tweets = [
        {"id": "1", "conversation_id": "1", "created_at": "2026-04-17T10:00:00Z", "text": "head"},
        {"id": "2", "conversation_id": "1", "created_at": "2026-04-17T10:05:00Z", "text": "reply1"},
        {"id": "3", "conversation_id": "1", "created_at": "2026-04-17T10:10:00Z", "text": "reply2"},
        {"id": "4", "conversation_id": "4", "created_at": "2026-04-17T11:00:00Z", "text": "standalone"},
    ]
    threads = _group_threads(tweets)
    assert len(threads) == 2
    # Threads sorted by head created_at
    assert threads[0][0]["id"] == "1"
    assert [t["id"] for t in threads[0]] == ["1", "2", "3"]
    assert threads[1][0]["id"] == "4"


def test_group_threads_no_conversation_id_falls_back_to_id():
    """Tweets without conversation_id are grouped as singletons by their own id."""
    tweets = [{"id": "1", "created_at": "2026-04-17T10:00:00Z", "text": "solo"}]
    threads = _group_threads(tweets)
    assert len(threads) == 1
    assert threads[0][0]["id"] == "1"


# --- URL expansion ---


def test_expand_urls_replaces_tco():
    """t.co links are rewritten to expanded_url when entities are present."""
    text = "check this out https://t.co/abc"
    entities = {"urls": [{"url": "https://t.co/abc", "expanded_url": "https://example.com/post"}]}
    assert _expand_urls(text, entities) == "check this out https://example.com/post"


def test_expand_urls_no_entities():
    """Text is unchanged when entities is None."""
    assert _expand_urls("hello", None) == "hello"


def test_expand_urls_empty_text():
    assert _expand_urls("", {"urls": []}) == ""


# --- Slugify ---


def test_slugify_strips_urls_and_punctuation():
    assert _slugify("Hello, World! https://t.co/xyz") == "hello-world"


def test_slugify_caps_length():
    out = _slugify("x" * 200, max_len=20)
    assert len(out) <= 20


def test_slugify_returns_untitled_for_empty():
    assert _slugify("") == "untitled"
    assert _slugify("!!!") == "untitled"


# --- Render one thread ---


def test_render_thread_single_tweet():
    tweet = {
        "id": "1001",
        "conversation_id": "1001",
        "author_id": AUTHOR_ID,
        "created_at": "2026-04-17T10:00:00Z",
        "text": "First line of the tweet\nwith more content",
        "entities": {},
    }
    result = _render_thread([tweet], "karpathy", "Andrej Karpathy", {}, {})
    assert result is not None
    content, meta = result
    assert meta["kind"] == "tweet"
    assert meta["tweet_id"] == "1001"
    assert meta["handle"] == "karpathy"
    assert "source: x" in content
    assert "kind: tweet" in content
    assert "# First line of the tweet" in content
    assert "@karpathy" in content
    assert "https://x.com/karpathy/status/1001" in content
    assert "First line of the tweet" in content


def test_render_thread_multi_tweet():
    thread = [
        {"id": "1", "conversation_id": "1", "author_id": AUTHOR_ID,
         "created_at": "2026-04-17T10:00:00Z", "text": "head"},
        {"id": "2", "conversation_id": "1", "author_id": AUTHOR_ID,
         "created_at": "2026-04-17T10:05:00Z", "text": "middle",
         "in_reply_to_user_id": AUTHOR_ID},
        {"id": "3", "conversation_id": "1", "author_id": AUTHOR_ID,
         "created_at": "2026-04-17T10:10:00Z", "text": "tail",
         "in_reply_to_user_id": AUTHOR_ID},
    ]
    result = _render_thread(thread, "user", "User", {}, {})
    assert result is not None
    content, meta = result
    assert meta["kind"] == "thread"
    assert meta["length"] == 3
    assert meta["tweet_id"] == "1"
    # Each tweet's text appears in body
    for line in ("head", "middle", "tail"):
        assert line in content


def test_render_thread_inlines_quoted_tweet():
    tweet = {
        "id": "1001",
        "conversation_id": "1001",
        "author_id": AUTHOR_ID,
        "created_at": "2026-04-17T10:00:00Z",
        "text": "great point",
        "referenced_tweets": [{"type": "quoted", "id": "500"}],
    }
    includes_tweets = {"500": {"id": "500", "author_id": "999", "text": "original insight"}}
    includes_users = {"999": {"id": "999", "username": "jane", "name": "Jane Doe"}}
    result = _render_thread([tweet], "karpathy", "Andrej Karpathy", includes_tweets, includes_users)
    assert result is not None
    content, _ = result
    assert "Quoting **@jane**" in content
    assert "original insight" in content


def test_render_thread_empty_returns_none():
    assert _render_thread([], "x", "x", {}, {}) is None


# --- Handles manifest ---


def test_handles_roundtrip(tmp_path):
    raw_dir = tmp_path / "x"
    raw_dir.mkdir()

    save_handles(raw_dir, {"alice": {"user_id": "1", "name": "Alice"}})
    assert load_handles(raw_dir) == {"alice": {"user_id": "1", "name": "Alice"}}


def test_load_handles_missing_returns_empty(tmp_path):
    assert load_handles(tmp_path / "x") == {}


def test_add_handle_uses_injected_resolver(tmp_path, monkeypatch):
    """add_handle hits resolve_handle; we stub it out to avoid network."""
    raw_dir = tmp_path / "x"
    raw_dir.mkdir()

    fake_user = {"id": "42", "username": "karpathy", "name": "Andrej"}
    monkeypatch.setattr(x_source, "resolve_handle", lambda username: fake_user)

    entry = add_handle(raw_dir, "karpathy")
    assert entry["user_id"] == "42"
    assert entry["name"] == "Andrej"

    # Idempotent: re-adding returns the same entry without another resolve call.
    def boom(_):
        raise AssertionError("should not be called for existing handle")
    monkeypatch.setattr(x_source, "resolve_handle", boom)
    entry2 = add_handle(raw_dir, "karpathy")
    assert entry2 == entry

    # user.json cached per handle
    cached = json.loads((raw_dir / "karpathy" / "user.json").read_text())
    assert cached["id"] == "42"


def test_remove_handle(tmp_path):
    raw_dir = tmp_path / "x"
    raw_dir.mkdir()
    save_handles(raw_dir, {"alice": {"user_id": "1"}, "bob": {"user_id": "2"}})
    assert remove_handle(raw_dir, "alice") is True
    assert "alice" not in load_handles(raw_dir)
    assert remove_handle(raw_dir, "alice") is False  # already gone


def test_remove_handle_strips_leading_at(tmp_path):
    raw_dir = tmp_path / "x"
    raw_dir.mkdir()
    save_handles(raw_dir, {"alice": {"user_id": "1"}})
    assert remove_handle(raw_dir, "@alice") is True


# --- Full render pipeline against stored raw data ---


def test_render_writes_files_and_index(tmp_path):
    raw_dir = tmp_path / "x"
    raw_dir.mkdir()
    save_handles(raw_dir, {"karpathy": {"user_id": "33836629", "name": "Andrej"}})

    handle_dir = raw_dir / "karpathy"
    handle_dir.mkdir()
    (handle_dir / "user.json").write_text(json.dumps({
        "id": "33836629", "username": "karpathy", "name": "Andrej"
    }))

    tweets = [
        {"id": "1", "conversation_id": "1", "author_id": "33836629",
         "created_at": "2026-04-17T10:00:00Z", "text": "thread head"},
        {"id": "2", "conversation_id": "1", "author_id": "33836629",
         "created_at": "2026-04-17T10:05:00Z", "text": "continuation",
         "in_reply_to_user_id": "33836629"},
        {"id": "3", "conversation_id": "3", "author_id": "33836629",
         "created_at": "2026-04-16T09:00:00Z", "text": "solo tweet"},
    ]
    jsonl = handle_dir / "tweets-2026-04.jsonl"
    jsonl.write_text("\n".join(json.dumps(t) for t in tweets) + "\n")

    readable_dir = tmp_path / "readable"
    stats = render(raw_dir, readable_dir)

    assert stats["generated"] == 2  # 1 thread + 1 solo
    assert stats["total"] == 3

    md_files = list(readable_dir.rglob("*.md"))
    md_files = [f for f in md_files if not f.name.startswith("_")]
    assert len(md_files) == 2

    index = (readable_dir / "_index.md").read_text()
    assert "@karpathy" in index
    assert "thread head" in index or "thread, 2" in index

    # Second render should be a no-op (all skipped)
    stats2 = render(raw_dir, readable_dir)
    assert stats2["generated"] == 0
    assert stats2["skipped"] == 2
