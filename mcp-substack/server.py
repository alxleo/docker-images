"""Substack MCP Server — read paid subscription content as markdown.

Tools:
  list_subscriptions - List user's Substack subscriptions
  list_posts         - Recent posts from a publication
  get_post           - Full post content as markdown
  search_posts       - Search within a publication

Auth: SUBSTACK_SID and SUBSTACK_USERNAME env vars (injected from Docker secrets).
"""

import json
import os
import tempfile

import markdownify
from mcp.server.fastmcp import FastMCP
from substack_api import Newsletter, Post, SubstackAuth, User

mcp = FastMCP("substack")


def _get_auth() -> SubstackAuth:
    """Build SubstackAuth from environment variables."""
    sid = os.environ.get("SUBSTACK_SID", "")
    if not sid:
        raise ValueError("SUBSTACK_SID not set — add the cookie as a Docker secret")

    # SubstackAuth expects a JSON cookies file — write a temp one
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
    auth = _get_auth()
    newsletter = Newsletter(publication_url, auth=auth)
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
    """
    auth = _get_auth()
    post = Post(post_url, auth=auth)
    meta = post.get_metadata()
    html_content = post.get_content()
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
    auth = _get_auth()
    newsletter = Newsletter(publication_url, auth=auth)
    posts = newsletter.search_posts(query, limit=limit)
    results = []
    for post in posts:
        meta = post.get_metadata()
        results.append(_post_to_dict(meta))
    return json.dumps(results, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
