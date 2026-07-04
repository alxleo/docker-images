#!/usr/bin/env python3
"""Reddit MCP — no Reddit API credentials required.

Why this exists: Reddit closed self-serve API access (Responsible Builder Policy,
Nov 2025; new credentials now require manual approval that personal/hobby use is
rarely granted) and blocks unauthenticated `.json` (403 since 2026-05-30). The old
OAuth `mcp-reddit` service is therefore dead and unrevivable without an approved app.

Two credential-free backends, each doing what it's best at:
  - **Reads** (read_thread, browse_subreddit) → Arctic-Shift
    (https://arctic-shift.photon-reddit.com), the community's free, no-auth,
    near-real-time archive with full comment trees.
  - **Search** (search_reddit) → the homelab's self-hosted SearXNG. Arctic-Shift's
    own full-text index is under maintenance, so global keyword search runs through
    SearXNG (site:reddit.com) and enriches hits with live post data via Arctic-Shift.

Run (stdio): SEARXNG_URL=http://localhost:8888 uv run --with mcp --with httpx python server.py
"""

from __future__ import annotations

import os
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

# Reddit search runs through the homelab's self-hosted SearXNG (Arctic-Shift's
# own full-text index is under maintenance). Same integration mcp-searxng uses:
# the container reaches it by Docker DNS on mcp-network.
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
_THREAD_RE = re.compile(r"reddit\.com/r/([^/]+)/comments/([0-9a-z]+)")

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


def _int(value: object) -> int:
    """Sort key: 0 for missing/None/non-int (score/created_utc can be JSON null or a '?' stub)."""
    return value if isinstance(value, int) else 0


# Reddit replaces the title/body of removed posts with these stubs. Heavily
# moderated subs (e.g. r/selfhosted) AutoMod-hold most *new* posts pending
# review, so an unfiltered "newest" listing is a wall of these — drop them.
_REMOVED_STUBS = {"[removed]", "[deleted]", "[ removed by moderator ]", "[ removed by reddit ]"}


def _is_removed(post: dict[str, Any]) -> bool:
    """True if a post was removed/deleted and carries no readable content."""
    if post.get("removed_by_category"):
        return True
    return _text(post.get("title")).lower() in _REMOVED_STUBS


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
    "Reddit search is temporarily unavailable — the SearXNG backend "
    f"({SEARXNG_URL}) did not respond. read_thread and browse_subreddit still work."
)


def _searxng_reddit(query: str, subreddit: str, want: int) -> list[dict[str, str]]:
    """Full-text Reddit search via the self-hosted SearXNG JSON API.

    Returns thread hits [{subreddit, id, title, url}] in SearXNG relevance order,
    deduped by submission id. Raises httpx.HTTPError if SearXNG is unreachable.
    """
    site = f"reddit.com/r/{subreddit}" if subreddit else "reddit.com"
    resp = _client.get(f"{SEARXNG_URL}/search", params={"q": f"{query} site:{site}", "format": "json"})
    resp.raise_for_status()
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in resp.json().get("results", []):
        match = _THREAD_RE.search(result.get("url", ""))
        if not match or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        hits.append({"subreddit": match.group(1), "id": match.group(2), "title": _text(result.get("title")), "url": result.get("url", "")})
        if len(hits) >= want:
            break
    return hits


@mcp.tool()
def search_reddit(query: str, subreddit: str = "", limit: int = 25, sort: str = "relevance") -> str:
    """Search all of Reddit by keyword. Optionally restrict to one `subreddit`.

    Runs a full-text search via the homelab's SearXNG, then enriches each hit with
    live post data (score, comment count) from Arctic-Shift. sort='relevance'
    (SearXNG ranking, default), 'top' (by score), or 'new' (most recent).
    """
    try:
        hits = _searxng_reddit(query, subreddit, min(limit * 2, API_MAX_LIMIT))
    except (httpx.HTTPError, ValueError):  # unreachable, or a non-JSON body (json.JSONDecodeError ⊂ ValueError)
        return SEARCH_UNAVAILABLE
    ids = ",".join(f"t3_{h['id']}" for h in hits)
    enriched = {p.get("id"): p for p in _get("/posts/ids", {"ids": ids})} if ids else {}
    posts = [_merge_hit(h, enriched.get(h["id"])) for h in hits]
    posts = [p for p in posts if not _is_removed(p)]
    if not posts:
        where = f" in r/{subreddit}" if subreddit else ""
        return f"No Reddit results for '{query}'{where}."
    if sort == "top":
        posts.sort(key=lambda p: _int(p.get("score")), reverse=True)
    elif sort == "new":
        posts.sort(key=lambda p: _int(p.get("created_utc")), reverse=True)
    return "\n\n".join(_post_line(p) for p in posts[:limit])


def _merge_hit(hit: dict[str, str], post: dict[str, Any] | None) -> dict[str, Any]:
    """Arctic-Shift post if it indexed the thread, else the SearXNG result as a stub."""
    if post is not None:
        return post
    return {
        "subreddit": hit["subreddit"],
        "title": hit["title"],
        "permalink": urlparse(hit["url"]).path,
        "score": "?",
        "num_comments": "?",
    }


@mcp.tool()
def browse_subreddit(subreddit: str, limit: int = 25, sort: str = "new") -> str:
    """List a subreddit's posts. sort='new' (recent) or 'top' (highest score among recent)."""
    posts = _recent_posts(subreddit, sort)
    if not posts:
        return f"No posts found in r/{subreddit}."
    return "\n\n".join(_post_line(p) for p in posts[:limit])


if __name__ == "__main__":
    mcp.run()
