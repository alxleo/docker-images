"""Substack MCP Server — read subscription content as markdown.

Tools:
  list_subscriptions - List user's Substack subscriptions (public API)
  list_posts         - Recent posts from a publication (public API)
  get_post           - Full post content as markdown
  search_posts       - Search within a publication (public API)

Auth:
  Metadata tools (list_subscriptions, list_posts, search_posts) work without auth.
  get_post for paid content delegates to crawl4ai (same Docker network) which
  authenticates via browser login using SUBSTACK_EMAIL + SUBSTACK_PASSWORD.

Env vars (injected from Docker secrets):
  SUBSTACK_EMAIL    - account email (for crawl4ai browser login on paid posts)
  SUBSTACK_PASSWORD - account password (for crawl4ai browser login on paid posts)
  SUBSTACK_USERNAME - profile handle (for list_subscriptions)
  CRAWL4AI_URL      - crawl4ai endpoint (default: http://crawl4ai:11235)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Any

import markdownify
import requests
from mcp.server.fastmcp import FastMCP
from substack_api import Newsletter, Post, User

mcp = FastMCP("substack")
log = logging.getLogger("substack-mcp")

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CRAWL4AI_URL = os.environ.get("CRAWL4AI_URL", "http://crawl4ai:11235")


def _post_to_dict(post_data: dict[str, Any]) -> dict[str, str | int]:
    """Extract useful fields from a raw post data dict."""
    return {
        "title": post_data.get("title", ""),
        "subtitle": post_data.get("subtitle", ""),
        "slug": post_data.get("slug", ""),
        "url": post_data.get("canonical_url", ""),
        "date": post_data.get("post_date", ""),
        "audience": post_data.get("audience", ""),
        "word_count": post_data.get("wordcount", 0),
        "description": post_data.get("description", ""),
    }


def _extract_slug(post_url: str) -> str:
    """Extract the post slug from a Substack URL."""
    path = urllib.parse.urlparse(post_url).path
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "p":
        return parts[1]
    return parts[-1]


def _extract_base_url(post_url: str) -> str:
    """Extract the publication base URL from a post URL."""
    parsed = urllib.parse.urlparse(post_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch_via_api(post_url: str) -> dict[str, Any] | None:
    """Fetch post metadata from the Substack API (unauthenticated).

    Returns metadata + body_html (full for free posts, truncated for paid).
    """
    slug = _extract_slug(post_url)
    base_url = _extract_base_url(post_url)
    api_url = f"{base_url}/api/v1/posts/{slug}"

    try:
        r = requests.get(api_url, headers={"Accept": "application/json", "User-Agent": CHROME_UA}, timeout=30)
        if r.status_code != 200:
            log.warning("API returned %d for %s", r.status_code, api_url)
            return None
        return r.json()
    except requests.RequestException as e:
        log.warning("API fetch failed: %s", e)
        return None


def _crawl4ai_request(url: str, session_id: str = "", js_code: str = "") -> dict[str, Any] | None:
    """Make a crawl4ai request. Returns the first result dict or None."""
    payload = {
        "urls": [url],
        "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
        "crawler_config": {
            "type": "CrawlerRunConfig",
            "params": {
                "wait_until": "networkidle",
                "page_timeout": 30000,
                "cache_mode": "bypass",
            },
        },
    }
    if session_id:
        payload["session_id"] = session_id
        payload["crawler_config"]["params"]["session_id"] = session_id
    if js_code:
        payload["crawler_config"]["params"]["js_code"] = js_code

    try:
        r = requests.post(f"{CRAWL4AI_URL}/crawl", json=payload, timeout=60)
        if r.status_code != 200:
            log.warning("crawl4ai returned %d: %s", r.status_code, r.text[:200])
            return None
        data = r.json()
        if isinstance(data.get("results"), list) and data["results"]:
            return data["results"][0]
        return data
    except requests.RequestException as e:
        log.warning("crawl4ai request failed: %s", e)
        return None


def _extract_crawl4ai_markdown(result: dict[str, Any]) -> str:
    """Extract raw markdown from a crawl4ai result."""
    md = result.get("markdown", "")
    if isinstance(md, dict):
        md = md.get("raw_markdown", md.get("markdown", ""))
    return str(md) if md else ""


class _Crawl4AISession:
    """Persistent crawl4ai browser session for Substack authentication.

    Logs in once, reuses the session across get_post calls.
    Re-logs in if a fetch returns only a preview (<500 words).
    """

    SESSION_ID = "substack-auth"

    def __init__(self) -> None:
        self.logged_in = False

    def login(self) -> bool:
        """Login to Substack via crawl4ai browser."""
        email = os.environ.get("SUBSTACK_EMAIL", "")
        password = os.environ.get("SUBSTACK_PASSWORD", "")
        if not all((email, password)):
            log.warning("SUBSTACK_EMAIL/PASSWORD not set — cannot authenticate for paid content")
            return False

        login_js = (
            'const r = await fetch("/api/v1/login", '
            '{method: "POST", headers: {"Content-Type": "application/json"}, '
            f'body: JSON.stringify({{redirect: "/", for_pub: "", email: "{email}", '
            f'password: "{password}", captcha_response: null}})}});'
        )
        result = _crawl4ai_request(
            "https://substack.com/sign-in", session_id=self.SESSION_ID, js_code=login_js,
        )
        if result and result.get("success"):
            self.logged_in = True
            log.info("crawl4ai: logged in to Substack")
            return True

        log.warning("crawl4ai: login failed")
        return False

    def fetch(self, post_url: str) -> str | None:
        """Fetch a post, logging in if needed. Retries once on preview."""
        if not self.logged_in and not self.login():
            return None

        post_result = _crawl4ai_request(post_url, session_id=self.SESSION_ID)
        if not post_result:
            return None

        md = _extract_crawl4ai_markdown(post_result)
        word_count = len(md.split()) if md else 0

        # Preview (<500 words) means session may have expired — retry once
        if word_count < 500:
            log.info("crawl4ai: only %d words — re-logging in and retrying", word_count)
            self.logged_in = False
            if not self.login():
                return md if word_count > 100 else None
            post_result = _crawl4ai_request(post_url, session_id=self.SESSION_ID)
            if not post_result:
                return md if word_count > 100 else None
            md = _extract_crawl4ai_markdown(post_result)
            word_count = len(md.split()) if md else 0

        if word_count > 100:
            log.info("crawl4ai: got content (%d words)", word_count)
            return md

        log.warning("crawl4ai: content too short (%d words)", word_count)
        return None


_crawl4ai_session = _Crawl4AISession()


def _fetch_via_crawl4ai(post_url: str) -> str | None:
    """Fetch full paid content via crawl4ai browser with persistent session."""
    return _crawl4ai_session.fetch(post_url)


def _build_header(meta: dict[str, Any]) -> str:
    """Build markdown header from post metadata."""
    header = f"# {meta.get('title', '')}\n"
    if meta.get("subtitle"):
        header += f"*{meta['subtitle']}*\n"
    header += f"\n**Date:** {meta.get('post_date', 'Unknown')} | **Words:** {meta.get('wordcount', 'N/A')}\n\n---\n\n"
    return header


@mcp.tool()
def list_subscriptions() -> str:
    """List the user's Substack subscriptions.

    Returns a list of publications the user subscribes to, including
    publication name, domain, and membership state (active/inactive).
    """
    username = os.environ.get("SUBSTACK_USERNAME", "")
    if not username:
        return "Error: SUBSTACK_USERNAME not set"
    user = User(username)
    subs = user.get_subscriptions()
    if not subs:
        return "No subscriptions found. Check SUBSTACK_USERNAME."
    return json.dumps(subs, indent=2, default=str)


@mcp.tool()
def list_posts(publication_url: str, limit: int = 10, sort: str = "new") -> str:
    """List recent posts from a Substack publication.

    Args:
        publication_url: Full URL of the Substack (e.g., "https://example.substack.com")
        limit: Maximum number of posts to return (default 10)
        sort: Sort order — "new", "top", or "pinned"
    """
    newsletter = Newsletter(publication_url)
    posts = newsletter.get_posts(sorting=sort, limit=limit)
    results = []
    for post in posts:
        meta = post.get_metadata()
        results.append(_post_to_dict(meta))
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
def get_post(post_url: str) -> str:
    """Get the full content of a Substack post as markdown.

    Args:
        post_url: Full URL of the post (e.g., "https://example.substack.com/p/post-slug")

    Returns the complete post content converted to markdown, including title and metadata.
    Works with paywalled posts if the user has an active subscription.

    Strategy:
    1. Fetch metadata from API (always works, metadata not truncated)
    2. If paid post: delegate to crawl4ai for JS-rendered full content
    3. If free post: use API body_html directly
    """
    # Get metadata + body from API (unauthenticated — metadata always available)
    api_data = _fetch_via_api(post_url)
    meta = api_data if api_data is not None else {}
    is_truncated = "truncated_body_text" in meta

    if is_truncated:
        # Paid content: API always truncates. Use crawl4ai for JS rendering.
        crawl_md = _fetch_via_crawl4ai(post_url)
        if crawl_md:
            return _build_header(meta) + crawl_md

    # Free content or crawl4ai unavailable: use API body_html
    html_content = ""
    if api_data and api_data.get("body_html"):
        html_content = api_data["body_html"]
    else:
        # Fallback: substack-api library
        post = Post(post_url)
        fallback_meta = post.get_metadata()
        if not meta:
            meta = fallback_meta
        raw_content = post.get_content()
        html_content = raw_content if raw_content else ""

    if not html_content:
        return f"# {meta.get('title', 'Unknown')}\n\n*Content unavailable — post may be paywalled and subscription not active.*"

    md_content = markdownify.markdownify(html_content, heading_style="ATX", strip=["img"])

    if is_truncated:
        return _build_header(meta) + "*Note: Content truncated — crawl4ai unavailable for full paid content.*\n\n" + md_content

    return _build_header(meta) + md_content


@mcp.tool()
def search_posts(publication_url: str, query: str, limit: int = 10) -> str:
    """Search for posts within a Substack publication.

    Args:
        publication_url: Full URL of the Substack (e.g., "https://example.substack.com")
        query: Search query string
        limit: Maximum number of results (default 10)
    """
    newsletter = Newsletter(publication_url)
    posts = newsletter.search_posts(query, limit=limit)
    results = []
    for post in posts:
        meta = post.get_metadata()
        results.append(_post_to_dict(meta))
    return json.dumps(results, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
