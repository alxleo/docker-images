"""Substack MCP Server — read paid subscription content as markdown.

Tools:
  list_subscriptions - List user's Substack subscriptions
  list_posts         - Recent posts from a publication
  get_post           - Full post content as markdown
  search_posts       - Search within a publication

Auth: Email/password login via Substack API. Session auto-refreshes on 401.
  SUBSTACK_EMAIL + SUBSTACK_PASSWORD env vars (injected from Docker secrets).
  SUBSTACK_USERNAME for listing subscriptions (Substack profile handle).

Paid content: The Substack API always truncates body_html for paid posts.
  get_post delegates to crawl4ai (same Docker network) for JS-rendered full content.
"""

import json
import logging
import os
import urllib.parse

import markdownify
import requests
from mcp.server.fastmcp import FastMCP
from substack_api import Newsletter, Post, SubstackAuth, User

mcp = FastMCP("substack")
log = logging.getLogger("substack-mcp")

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CRAWL4AI_URL = os.environ.get("CRAWL4AI_URL", "http://crawl4ai:11235")

# Global session — refreshed on login, reused across requests
_session: requests.Session | None = None
_sid_cookie: str | None = None


def _login() -> requests.Session:
    """Authenticate via email/password, return a session with valid cookies."""
    global _session, _sid_cookie

    email = os.environ.get("SUBSTACK_EMAIL", "")
    password = os.environ.get("SUBSTACK_PASSWORD", "")
    if not email or not password:
        raise ValueError("SUBSTACK_EMAIL and SUBSTACK_PASSWORD must be set")

    session = requests.Session()
    session.headers["User-Agent"] = CHROME_UA

    r = session.post(
        "https://substack.com/api/v1/login",
        json={"redirect": "/", "for_pub": "", "email": email, "password": password, "captcha_response": None},
        timeout=30,
    )

    if r.status_code == 401:
        raise ValueError("Substack login failed — check email/password")
    if r.status_code == 403:
        error_msg = r.text[:200]
        if "captcha" in error_msg.lower():
            raise ValueError("Substack login requires CAPTCHA — try again later or use cookie-based auth")
        raise ValueError(f"Substack login forbidden: {error_msg}")
    r.raise_for_status()

    # Extract the session cookie
    sid = session.cookies.get("substack.sid", domain=".substack.com")
    if not sid:
        sid = session.cookies.get("connect.sid", domain=".substack.com")
    if not sid:
        # Check all cookies
        for cookie in session.cookies:
            if cookie.name in ("substack.sid", "connect.sid"):
                sid = cookie.value
                break

    if not sid:
        raise ValueError("Login succeeded but no session cookie received")

    log.info("Logged in to Substack as %s", email)
    _session = session
    _sid_cookie = sid
    return session


def _get_session() -> requests.Session:
    """Get an authenticated session, logging in if needed."""
    global _session
    if _session is None:
        _login()
    return _session


def _get_sid() -> str:
    """Get the current session cookie value (for passing to crawl4ai)."""
    global _sid_cookie
    if _sid_cookie is None:
        _login()
    return _sid_cookie


def _authed_get(url: str, **kwargs) -> requests.Response:
    """GET with auto re-login on 401/403."""
    session = _get_session()
    r = session.get(url, timeout=kwargs.pop("timeout", 30), **kwargs)
    if r.status_code in (401, 403):
        log.info("Session expired, re-logging in")
        _login()
        session = _get_session()
        r = session.get(url, timeout=30, **kwargs)
    return r


def _get_substack_auth() -> SubstackAuth:
    """Build SubstackAuth for the substack-api library using our session cookie."""
    import tempfile

    sid = _get_sid()
    cookies = [
        {"name": "substack.sid", "value": sid, "domain": ".substack.com", "path": "/", "secure": True},
    ]
    cookies_file = os.path.join(tempfile.gettempdir(), "substack_cookies.json")
    with open(cookies_file, "w") as f:
        json.dump(cookies, f)
    return SubstackAuth(cookies_file)


def _post_to_dict(post_data: dict) -> dict:
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


def _fetch_via_api(post_url: str) -> dict | None:
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
    except Exception as e:
        log.warning("API fetch failed: %s", e)
        return None


def _crawl4ai_request(url: str, session_id: str = "", js_code: str = "") -> dict | None:
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
    except Exception as e:
        log.warning("crawl4ai request failed: %s", e)
        return None


def _fetch_via_crawl4ai(post_url: str) -> str | None:
    """Fetch full paid content via crawl4ai two-step browser login.

    Step 1: Navigate to substack.com/sign-in, execute login via JS fetch()
    Step 2: Navigate to the post page with the authenticated session
    Full content renders via client-side JS (server-side always truncates paid posts).
    """
    email = os.environ.get("SUBSTACK_EMAIL", "")
    password = os.environ.get("SUBSTACK_PASSWORD", "")
    if not email or not password:
        log.warning("SUBSTACK_EMAIL/PASSWORD not set — cannot authenticate for paid content")
        return None

    session_id = "substack-auth"

    # Step 1: Login via browser JS
    login_js = (
        'const r = await fetch("/api/v1/login", '
        '{method: "POST", headers: {"Content-Type": "application/json"}, '
        f'body: JSON.stringify({{redirect: "/", for_pub: "", email: "{email}", '
        f'password: "{password}", captcha_response: null}})}});'
    )
    login_result = _crawl4ai_request("https://substack.com/sign-in", session_id=session_id, js_code=login_js)
    if not login_result or not login_result.get("success"):
        log.warning("crawl4ai login step failed")
        return None

    # Step 2: Fetch the post with the authenticated session
    post_result = _crawl4ai_request(post_url, session_id=session_id)
    if not post_result:
        return None

    md = post_result.get("markdown", "")
    if isinstance(md, dict):
        md = md.get("raw_markdown", md.get("markdown", ""))

    if md and len(md.split()) > 100:
        log.info("crawl4ai: got content (%d words)", len(md.split()))
        return md

    log.warning("crawl4ai: content too short (%d words)", len(str(md).split()))
    return None


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
    # Auth not needed for listing post metadata (titles, dates, etc.)
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
    # Get metadata + body from API
    api_data = _fetch_via_api(post_url)
    meta = api_data or {}
    is_paid = meta.get("audience") == "only_paid"
    is_truncated = "truncated_body_text" in (api_data or {})

    html_content = ""

    if is_paid or is_truncated:
        # Paid content: API always truncates. Use crawl4ai for JS rendering.
        crawl_md = _fetch_via_crawl4ai(post_url)
        if crawl_md:
            header = f"# {meta.get('title', '')}\n"
            if meta.get("subtitle"):
                header += f"*{meta['subtitle']}*\n"
            header += f"\n**Date:** {meta.get('post_date', 'Unknown')} | **Words:** {meta.get('wordcount', 'N/A')}\n\n---\n\n"
            return header + crawl_md

    # Free content or crawl4ai failed: use API body_html
    if api_data and api_data.get("body_html"):
        html_content = api_data["body_html"]
    else:
        # Last resort: substack-api library (unauthenticated — may be truncated)
        post = Post(post_url)
        if not meta:
            meta = post.get_metadata()
        html_content = post.get_content() or ""

    if not html_content:
        return f"# {meta.get('title', 'Unknown')}\n\n*Content unavailable — post may be paywalled and subscription not active.*"

    md_content = markdownify.markdownify(html_content, heading_style="ATX", strip=["img"])

    header = f"# {meta.get('title', '')}\n"
    if meta.get("subtitle"):
        header += f"*{meta['subtitle']}*\n"
    header += f"\n**Date:** {meta.get('post_date', 'Unknown')} | **Words:** {meta.get('wordcount', 'N/A')}\n\n---\n\n"

    return header + md_content


@mcp.tool()
def search_posts(publication_url: str, query: str, limit: int = 10) -> str:
    """Search for posts within a Substack publication.

    Args:
        publication_url: Full URL of the Substack (e.g., "https://example.substack.com")
        query: Search query string
        limit: Maximum number of results (default 10)
    """
    # Auth not needed for searching post metadata
    newsletter = Newsletter(publication_url)
    posts = newsletter.search_posts(query, limit=limit)
    results = []
    for post in posts:
        meta = post.get_metadata()
        results.append(_post_to_dict(meta))
    return json.dumps(results, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
