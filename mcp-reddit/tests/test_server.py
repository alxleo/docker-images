"""Unit tests for the Arctic-Shift Reddit MCP (pure logic, no network).

Loads the server module by path inside a module-scoped fixture (same pattern as
the homelab repo test pattern) so an import-time failure skips cleanly
instead of aborting collection. Skips if the mcp SDK isn't installed.
"""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed")
pytest.importorskip("httpx", reason="httpx not installed")

SERVER = Path(__file__).parent.parent / "server.py"


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location("reddit_arctic_server", SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.reddit.com/r/homelab/comments/1mulwz7/the_most_favorite/", "1mulwz7"),
        ("https://old.reddit.com/r/x/comments/abc123/", "abc123"),
        ("https://reddit.com/r/x/comments/abc123/title/?ref=share&utm_source=x", "abc123"),
        ("https://redd.it/1abc234", "1abc234"),
        ("redd.it/1abc234?utm_source=share", "1abc234"),
        ("t3_1mulwz7", "1mulwz7"),
        ("1mulwz7", "1mulwz7"),
    ],
)
def test_submission_id(server, value, expected):
    assert server.submission_id(value) == expected


def test_submission_id_rejects_share_links(server):
    with pytest.raises(ValueError, match="share link"):
        server.submission_id("https://www.reddit.com/r/homelab/s/AbCdEfGhIj")


def test_format_post_includes_title_score_body(server):
    out = server._format_post(
        {
            "subreddit": "homelab",
            "title": "Title",
            "author": "u",
            "score": 5,
            "num_comments": 2,
            "permalink": "/r/homelab/comments/x/",
            "selftext": "the body",
        }
    )
    assert "r/homelab — Title" in out
    assert "score 5" in out
    assert "the body" in out


def test_post_line_compact(server):
    out = server._post_line(
        {"subreddit": "homelab", "title": "Title", "score": 5, "num_comments": 2, "permalink": "/p"}
    )
    assert "r/homelab | Title" in out
    assert "reddit.com/p" in out


def test_long_comment_gets_ellipsis(server, monkeypatch):
    def fake_get(path, params):
        if path == "/posts/ids":
            return [{"subreddit": "x", "title": "t", "author": "a", "permalink": "/p"}]
        return [{"author": "c", "score": 1, "body": "x" * (server.COMMENT_BODY_MAX + 50)}]

    monkeypatch.setattr(server, "_get", fake_get)
    out = server.read_thread("1abc234", comment_limit=5)
    assert "…" in out


def test_api_limits_capped_at_max(server, monkeypatch):
    """Arctic-Shift rejects limit>100 with HTTP 400 — every fetch must stay capped."""
    captured = {}

    def fake_get(path, params):
        captured[path] = params
        if path == "/posts/ids":
            return [{"subreddit": "x", "title": "t", "author": "a", "permalink": "/p"}]
        return []

    monkeypatch.setattr(server, "_get", fake_get)

    server.read_thread("1abc234", comment_limit=100)
    assert captured["/comments/search"]["limit"] <= server.API_MAX_LIMIT

    server.search_reddit("q", subreddit="homelab", limit=80, sort="top")
    assert captured["/posts/search"]["limit"] <= server.API_MAX_LIMIT

    server.browse_subreddit("homelab", limit=500)
    assert captured["/posts/search"]["limit"] <= server.API_MAX_LIMIT

    server.browse_subreddit("homelab", limit=80, sort="top")
    assert captured["/posts/search"]["limit"] <= server.API_MAX_LIMIT


def test_listing_never_sends_text_query(server, monkeypatch):
    """Upstream text search (query/title/selftext) is under maintenance (503) —
    listing must only ever filter by subreddit, never send those params."""
    captured = {}
    monkeypatch.setattr(server, "_get", lambda path, params: captured.update(params) or [])
    server.browse_subreddit("homelab")
    assert set(captured) <= {"subreddit", "limit", "sort"}
    captured.clear()
    server.search_reddit("docker", subreddit="homelab")
    assert set(captured) <= {"subreddit", "limit", "sort"}


REMOVED = {"removed_by_category": "moderator", "title": "[ Removed by moderator ]", "score": 1}
LIVE = {"title": "Real post about docker", "selftext": "compose stack", "score": 9, "subreddit": "s", "permalink": "/p"}


def test_is_removed_classifies(server):
    assert server._is_removed(REMOVED) is True
    assert server._is_removed({"title": "[deleted]"}) is True
    assert server._is_removed(LIVE) is False


def test_browse_filters_removed_posts(server, monkeypatch):
    monkeypatch.setattr(server, "_get", lambda path, params: [REMOVED, LIVE, dict(REMOVED)])
    out = server.browse_subreddit("s")
    assert "Removed by moderator" not in out
    assert "Real post about docker" in out


def test_browse_all_removed_returns_empty_msg(server, monkeypatch):
    monkeypatch.setattr(server, "_get", lambda path, params: [REMOVED, dict(REMOVED)])
    assert server.browse_subreddit("selfhosted") == "No posts found in r/selfhosted."


def test_search_requires_subreddit(server):
    assert server.search_reddit("docker") == server.SEARCH_UNAVAILABLE


def test_search_keyword_filters_recent_window(server, monkeypatch):
    posts = [LIVE, {"title": "unrelated", "selftext": "", "score": 3, "subreddit": "s", "permalink": "/q"}]
    monkeypatch.setattr(server, "_get", lambda path, params: posts)
    out = server.search_reddit("docker compose", subreddit="s")
    assert "Real post about docker" in out
    assert "unrelated" not in out


def test_search_no_match_explains_window(server, monkeypatch):
    monkeypatch.setattr(server, "_get", lambda path, params: [LIVE])
    out = server.search_reddit("kubernetes", subreddit="s")
    assert "No recent posts" in out and "most recent" in out
