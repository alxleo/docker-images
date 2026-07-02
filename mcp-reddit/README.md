# mcp-reddit (Arctic-Shift backend)

Reddit MCP backed by **Arctic-Shift** — programmatic Reddit read access with **no Reddit API credentials**.

## Why

Reddit closed self-serve API access (Responsible Builder Policy, Nov 2025; new
credentials now require manual approval that personal/hobby use is rarely granted)
and returns **403 on unauthenticated `.json`** (since 2026-05-30). The old OAuth
`mcp-reddit` service is therefore dead and unrevivable without an approved app.
[Arctic-Shift](https://arctic-shift.photon-reddit.com) is the community's free,
no-auth, near-real-time Reddit archive (newest posts indexed within minutes) with
full comment trees — so programmatic Reddit reads work again with zero credentials.

## Tools

| Tool | Purpose |
|------|---------|
| `read_thread(url_or_id, comment_limit=40)` | A thread's post + its top comments (by score) |
| `search_reddit(query, subreddit="", limit=25, sort="new"\|"top")` | Full-text post search, optionally within one subreddit |
| `browse_subreddit(subreddit, limit=25, sort="new"\|"top")` | List a subreddit's posts |

## Run

```bash
uv run --no-project --with mcp --with httpx python server.py   # stdio MCP server
```

Ships as `ghcr.io/alxleo/mcp-reddit:latest` — mcp-proxy HTTP bridge on :8080 with `/ping`.

## Limitation

Arctic-Shift snapshots comments near post time, so comment **scores are early
values** (a comment showing "3" here may be "69" on live Reddit) and very fresh
comments on hot threads can lag by minutes. Post/search/browse listings are
near-live; comment *content* is complete, but vote counts are approximate.
The API caps every fetch at 100 rows and sorts only by recency, so on threads
with hundreds of comments "top by score" ranks the ~100 newest, and `sort="top"`
listings rank a recent window — not all-time. Reddit share links (`/s/…`) hide
the post id behind a redirect and are rejected with a clear error.
Read-only by design — Arctic-Shift cannot post, vote, or comment.
