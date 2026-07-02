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


def _list_posts(limit: int, sort: str, empty_msg: str, *, subreddit: str = "", query: str = "") -> str:
    # Arctic-Shift sorts only by created_utc; "top" = rank a wider recent window by score.
    fetch = min(limit * 4 if sort == "top" else limit, API_MAX_LIMIT)
    posts = _get("/posts/search", {"query": query, "subreddit": subreddit, "limit": fetch, "sort": "desc"})
    if not posts:
        return empty_msg
    if sort == "top":
        posts.sort(key=lambda p: p.get("score", 0), reverse=True)
        posts = posts[:limit]
    return "\n\n".join(_post_line(p) for p in posts)


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


@mcp.tool()
def search_reddit(query: str, subreddit: str = "", limit: int = 25, sort: str = "new") -> str:
    """Search Reddit posts by text. sort='new' (recent) or 'top' (highest score among recent).
    Optionally restrict to a single subreddit.
    """
    return _list_posts(limit, sort, "No results.", subreddit=subreddit, query=query)


@mcp.tool()
def browse_subreddit(subreddit: str, limit: int = 25, sort: str = "new") -> str:
    """List a subreddit's posts. sort='new' (recent) or 'top' (highest score among recent)."""
    return _list_posts(limit, sort, f"No posts found in r/{subreddit}.", subreddit=subreddit)


if __name__ == "__main__":
    mcp.run()
