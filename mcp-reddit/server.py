#!/usr/bin/env python3
"""Reddit MCP backed by Arctic-Shift — no Reddit API credentials required.

Why this exists: Reddit closed self-serve API access (Responsible Builder Policy,
Nov 2025; new credentials now require manual approval that personal/hobby use is
rarely granted) and blocks unauthenticated `.json` (403 since 2026-05-30). The old
OAuth `mcp-reddit` service is therefore dead and unrevivable without an approved
app. Arctic-Shift (https://arctic-shift.photon-reddit.com) is the community's
free, no-auth, near-real-time Reddit archive (newest posts indexed within minutes)
with full comment trees. This server exposes its API as MCP tools, so programmatic
Reddit read access works again with zero credentials.

Run (stdio): uv run --with mcp --with httpx python server.py
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx  # dependency of the mcp SDK — no extra install
from mcp.server.fastmcp import FastMCP

API = "https://arctic-shift.photon-reddit.com/api"
USER_AGENT = "homelab-reddit-arctic-mcp/1.0"
TIMEOUT = 25
API_MAX_LIMIT = 100  # Arctic-Shift rejects limit outside 1..100 with HTTP 400
COMMENT_BODY_MAX = 600
MAX_ATTEMPTS = 2

SHARE_LINK_ERROR = (
    "This is a Reddit share link (/s/…); the real post id hides behind a redirect "
    "this server can't follow. Open it in a browser and pass the expanded "
    "…/comments/<id>/… URL instead."
)

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)

mcp = FastMCP("reddit")


def _text(value: object) -> str:
    """None-safe str: Arctic-Shift returns JSON null for deleted selftext/body."""
    return value.strip() if isinstance(value, str) else ""


# Reddit replaces the title/body of removed posts with these stubs. Heavily
# moderated subs (e.g. r/selfhosted) AutoMod-hold most *new* posts pending
# review, so an unfiltered "newest" listing is a wall of these — drop them.
_REMOVED_STUBS = {"[removed]", "[deleted]", "[ removed by moderator ]", "[ removed by reddit ]"}


def _is_removed(post: dict[str, Any]) -> bool:
    """True if a post was removed/deleted and carries no readable content."""
    if post.get("removed_by_category"):
        return True
    return _text(post.get("title")).lower() in _REMOVED_STUBS


def _matches(post: dict[str, Any], terms: list[str]) -> bool:
    """True if every search term appears in the post's title or selftext."""
    haystack = f"{_text(post.get('title'))} {_text(post.get('selftext'))}".lower()
    return all(term in haystack for term in terms)


def _get(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """GET an Arctic-Shift endpoint, returning the `data` list (empty on miss).

    Retries once: Arctic-Shift's cold path can exceed the timeout (~9s observed),
    but it warms a server-side cache, so the retry typically returns in <100ms.
    """
    query = {k: v for k, v in params.items() if v not in (None, "", [])}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _client.get(f"{API}{path}", params=query)
            resp.raise_for_status()
        except httpx.TimeoutException:
            if attempt == MAX_ATTEMPTS:
                raise
        except httpx.HTTPStatusError as exc:
            # 4xx won't improve on retry — only retry 5xx
            if attempt == MAX_ATTEMPTS or not exc.response.is_server_error:
                raise
        else:
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else payload
            return data or []
    unreachable = "retry loop always returns or raises"
    raise AssertionError(unreachable)


def submission_id(url_or_id: str) -> str:
    """Extract a base-36 submission id from a thread URL or a bare/`t3_`-prefixed id."""
    text = url_or_id.strip()
    if "/" not in text and "." not in text:
        return text.removeprefix("t3_")  # bare id
    if re.search(r"/s/[A-Za-z0-9]+", text):
        raise ValueError(SHARE_LINK_ERROR)
    # urlparse needs a scheme to split path from query string
    path = urlparse(text if "://" in text else f"https://{text}").path
    match = re.search(r"/comments/([0-9a-z]+)", path)
    if match:
        return match.group(1)
    # redd.it/<id> shortlinks and other single-segment paths
    return path.split("t3_")[-1].strip("/").split("/")[-1]


def _format_post(post: dict[str, Any]) -> str:
    body = _text(post.get("selftext"))
    header = (
        f"r/{post.get('subreddit')} — {post.get('title', '')}\n"
        f"by u/{post.get('author')} | score {post.get('score', '?')} | "
        f"{post.get('num_comments', '?')} comments\n"
        f"https://reddit.com{post.get('permalink', '')}"
    )
    return f"{header}\n\n{body}" if body else header


def _post_line(post: dict[str, Any]) -> str:
    return (
        f"r/{post.get('subreddit')} | {post.get('title', '')} "
        f"(score {post.get('score', '?')}, {post.get('num_comments', '?')} comments)\n"
        f"https://reddit.com{post.get('permalink', '')}"
    )


def _recent_posts(subreddit: str, sort: str) -> list[dict[str, Any]]:
    """Fetch the recent post window for a subreddit, minus removed/deleted posts.

    Always over-fetches to API_MAX_LIMIT: after dropping mod-removed posts the
    readable remainder can be thin, and "top" needs a wide window to rank.
    Arctic-Shift sorts only by created_utc (`sort=desc` = newest first).
    """
    posts = _get("/posts/search", {"subreddit": subreddit, "limit": API_MAX_LIMIT, "sort": "desc"})
    posts = [p for p in posts if not _is_removed(p)]
    if sort == "top":
        posts.sort(key=lambda p: p.get("score", 0), reverse=True)
    return posts


@mcp.tool()
def read_thread(url_or_id: str, comment_limit: int = 40) -> str:
    """Read a Reddit thread — the post plus its top comments (by score).

    url_or_id: a thread URL (…/comments/<id>/…) or the bare submission id.
    """
    sid = submission_id(url_or_id)
    posts = _get("/posts/ids", {"ids": f"t3_{sid}"})
    if not posts:
        return f"No post found for id '{sid}'. Arctic-Shift may not have indexed it yet."
    out = [_format_post(posts[0]), "\n--- Comments (top by score) ---"]
    comments = _get(
        "/comments/search",
        {"link_id": f"t3_{sid}", "limit": min(comment_limit * 2, API_MAX_LIMIT), "sort": "desc"},
    )
    comments.sort(key=lambda c: c.get("score", 0), reverse=True)
    shown = 0
    for c in comments:
        body = _text(c.get("body")).replace("\n", " ")
        if not body or body in ("[deleted]", "[removed]"):
            continue
        snippet = body[:COMMENT_BODY_MAX] + ("…" if len(body) > COMMENT_BODY_MAX else "")
        out.append(f"• u/{c.get('author')} ({c.get('score', '?')}): {snippet}")
        shown += 1
        if shown >= comment_limit:
            break
    return "\n".join(out)


SEARCH_UNAVAILABLE = (
    "Reddit full-text search is unavailable — Arctic-Shift's search index (the "
    "query/title/selftext filters) is under maintenance and returns HTTP 503. "
    "Pass a `subreddit` to keyword-filter its recent posts instead, or use "
    "browse_subreddit / read_thread."
)


@mcp.tool()
def search_reddit(query: str, subreddit: str = "", limit: int = 25, sort: str = "new") -> str:
    """Search a subreddit's recent posts by keyword. sort='new' or 'top' (by score).

    Arctic-Shift's server-side full-text index is under maintenance, so this
    matches `query` terms against the ~100 most recent posts of `subreddit`
    client-side. A `subreddit` is required; global text search is unavailable.
    """
    if not subreddit:
        return SEARCH_UNAVAILABLE
    terms = query.lower().split()
    posts = _recent_posts(subreddit, sort)
    hits = [p for p in posts if _matches(p, terms)]
    if not hits:
        return (
            f"No recent posts in r/{subreddit} matching '{query}'. (Search is limited "
            "to the ~100 most recent posts while Arctic-Shift's full-text index is down.)"
        )
    return "\n\n".join(_post_line(p) for p in hits[:limit])


@mcp.tool()
def browse_subreddit(subreddit: str, limit: int = 25, sort: str = "new") -> str:
    """List a subreddit's posts. sort='new' (recent) or 'top' (highest score among recent)."""
    posts = _recent_posts(subreddit, sort)
    if not posts:
        return f"No posts found in r/{subreddit}."
    return "\n\n".join(_post_line(p) for p in posts[:limit])


if __name__ == "__main__":
    mcp.run()
