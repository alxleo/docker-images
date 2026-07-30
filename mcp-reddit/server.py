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

Run (HTTP): SEARXNG_URL=http://localhost:8888 uv run python server.py
"""

from __future__ import annotations

import html
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx  # dependency of the mcp SDK — no extra install
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import PlainTextResponse

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

# Reddit's own search — for subreddit-scoped queries. Reddit blocks unauth .json
# (403) but still serves .rss to residential IPs (this container's egress runs on
# the homelab's residential line, so it works where a datacenter IP wouldn't). It's
# rate-limited (429 under load), so it's tried first for freshness and falls back
# to SearXNG on any failure. Reddit requires a unique descriptive User-Agent.
REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.rss"
REDDIT_UA = "mcp-reddit/2.0 (homelab feed reader; +https://github.com/alxleo/docker-images)"
_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)

# Fallback search when SearXNG is unreachable: PullPush (Pushshift mirror, native
# Reddit objects). It's a *historical archive* — its index lags live Reddit by
# many months — so it is fallback-only and its results are labelled as dated.
PULLPUSH_API = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_STALE_NOTE = "⚠️ SearXNG unavailable — showing PullPush archive results (a historical mirror; may be months out of date):"

SHARE_LINK_ERROR = (
    "This is a Reddit share link (/s/…); the real post id hides behind a redirect "
    "this server can't follow. Open it in a browser and pass the expanded "
    "…/comments/<id>/… URL instead."
)

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)

mcp = MCPServer("reddit", version="1.3.1")


@mcp.custom_route("/ping", methods=["GET"], include_in_schema=False)
async def ping(_request: Request) -> PlainTextResponse:
    """Compatibility health route for the homelab Caddy and Gatus contract."""
    return PlainTextResponse("pong")


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
    "Reddit search is temporarily unavailable — both the SearXNG backend "
    f"({SEARXNG_URL}) and the PullPush fallback failed to respond. "
    "read_thread and browse_subreddit still work."
)


def _reddit_native_search(subreddit: str, query: str, sort: str, want: int) -> list[dict[str, str]]:
    """Subreddit search via Reddit's own search.rss (native, freshest source).

    Returns thread hits [{subreddit, id, title, url}]. Raises httpx.HTTPError on a
    non-200 (notably 429 rate-limit or 403) so the caller falls back to SearXNG.
    """
    sort_val = sort if sort in ("relevance", "top", "new") else "relevance"
    params = {"q": query, "restrict_sr": "1", "sort": sort_val, "limit": str(min(want, 25))}
    resp = _client.get(
        REDDIT_SEARCH_URL.format(subreddit=subreddit), params=params, headers={"User-Agent": REDDIT_UA}
    )
    resp.raise_for_status()
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in _ENTRY_RE.findall(resp.text):
        match = _THREAD_RE.search(entry)
        if not match or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        title = _TITLE_RE.search(entry)
        hits.append({
            "subreddit": match.group(1),
            "id": match.group(2),
            "title": html.unescape(title.group(1).strip()) if title else "",
            "url": f"https://www.reddit.com/r/{match.group(1)}/comments/{match.group(2)}/",
        })
        if len(hits) >= want:
            break
    return hits


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


def _enrich_and_format(hits: list[dict[str, str]], subreddit: str, query: str, limit: int, sort: str) -> str:
    """Enrich search hits with live Arctic-Shift post data, drop removed, sort, render."""
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


@mcp.tool()
def search_reddit(query: str, subreddit: str = "", limit: int = 25, sort: str = "relevance") -> str:
    """Search all of Reddit by keyword. Optionally restrict to one `subreddit`.

    Sources, in order: for a subreddit-scoped query, Reddit's own search.rss
    (native, freshest); else / on failure, the self-hosted SearXNG; then PullPush.
    Hits are enriched with live score + comment counts from Arctic-Shift.
    sort='relevance' (default), 'top' (by score), or 'new' (most recent).
    """
    want = min(limit * 2, API_MAX_LIMIT)
    # Subreddit-scoped: Reddit's own search is native + freshest. Its .rss works
    # from this container's residential egress (unlike .json); rate-limited, so
    # any failure (429/403/parse) silently falls through to SearXNG.
    if subreddit:
        try:
            hits = _reddit_native_search(subreddit, query, sort, want)
            if hits:
                return _enrich_and_format(hits, subreddit, query, limit, sort)
        except (httpx.HTTPError, ValueError):
            pass
    try:
        hits = _searxng_reddit(query, subreddit, want)
    except (httpx.HTTPError, ValueError):  # unreachable, or a non-JSON body (json.JSONDecodeError ⊂ ValueError)
        return _pullpush_fallback(query, subreddit, limit, sort)
    return _enrich_and_format(hits, subreddit, query, limit, sort)


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


def _pullpush_fallback(query: str, subreddit: str, limit: int, sort: str) -> str:
    """Search via PullPush when SearXNG is down. PullPush returns native (Pushshift-
    schema) posts, so no enrichment is needed — but it's a dated archive, hence the note.
    """
    params = {"q": query, "size": min(limit, API_MAX_LIMIT), "sort": "desc"}
    if subreddit:
        params["subreddit"] = subreddit
    try:
        resp = _client.get(PULLPUSH_API, params=params)
        resp.raise_for_status()
        posts = [p for p in resp.json().get("data", []) if not _is_removed(p)]
    except (httpx.HTTPError, ValueError):
        return SEARCH_UNAVAILABLE
    if not posts:
        return SEARCH_UNAVAILABLE
    if sort == "top":
        posts.sort(key=lambda p: _int(p.get("score")), reverse=True)
    return "\n\n".join([PULLPUSH_STALE_NOTE, *(_post_line(p) for p in posts[:limit])])


@mcp.tool()
def browse_subreddit(subreddit: str, limit: int = 25, sort: str = "new") -> str:
    """List a subreddit's posts. sort='new' (recent) or 'top' (highest score among recent)."""
    posts = _recent_posts(subreddit, sort)
    if not posts:
        return f"No posts found in r/{subreddit}."
    return "\n\n".join(_post_line(p) for p in posts[:limit])


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "8080")),
        json_response=True,
        stateless_http=True,
    )
