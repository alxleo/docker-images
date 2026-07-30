# mcp-reddit

Reddit MCP with **no Reddit API credentials** — reads via Arctic-Shift, search via SearXNG.

## Why

Reddit closed self-serve API access (Responsible Builder Policy, Nov 2025; new
credentials now require manual approval that personal/hobby use is rarely granted)
and returns **403 on unauthenticated `.json`** (since 2026-05-30). The old OAuth
`mcp-reddit` service is therefore dead and unrevivable without an approved app.
Two credential-free backends replace it, each doing what it's best at:

- **Reads** → [Arctic-Shift](https://arctic-shift.photon-reddit.com), the community's
  free, no-auth, near-real-time archive with full comment trees.
- **Search** → the homelab's self-hosted **SearXNG** (Arctic-Shift's own full-text
  index is under maintenance — see below).

## Tools

| Tool | Purpose |
|------|---------|
| `read_thread(url_or_id, comment_limit=40)` | A thread's post + its top comments (by score) |
| `search_reddit(query, subreddit="", limit=25, sort="relevance"\|"top"\|"new")` | Full-text search across Reddit (or one subreddit), enriched with live post data |
| `browse_subreddit(subreddit, limit=25, sort="new"\|"top")` | List a subreddit's posts (removed/deleted filtered out) |

## Run

```bash
SEARXNG_URL=http://localhost:8888 uv run --frozen python server.py
```

Ships as `ghcr.io/alxleo/mcp-reddit:latest` with native Streamable HTTP at
`http://localhost:8080/mcp`. Dependencies are locked and the runtime is Python
3.14; Node.js, `mcp-proxy`, and `mcp-filter` are not present.
`GET /ping` returns `pong` for compatibility with external load-balancer and
fleet health checks; Docker health still performs a real MCP initialize.
`SEARXNG_URL` defaults to `http://searxng:8080` (the homelab SearXNG on `mcp-network`).

## Search

Reddit's `.json` API is closed (403) and Arctic-Shift's own full-text index is under
maintenance (503) — but Reddit still serves **`.rss`** to residential IPs. `search_reddit`
therefore layers three credential-free sources:

1. **Subreddit-scoped** (`subreddit` given) → **Reddit's own `search.rss`** — native and
   freshest. Reddit blocks `.json` but serves `.rss` from a residential IP (this container's
   egress); it's rate-limited, so any failure (429/403) silently falls through to (2).
2. **Global / fallback** → the self-hosted **SearXNG** (`site:reddit.com`, aggregating
   Google/Bing/…).
3. **SearXNG down** → **PullPush** archive (labelled as dated).

All hits are enriched with live score + comment counts from Arctic-Shift's `/posts/ids`
(that endpoint works; only its *search* index is down). `sort="top"`/`"new"` rerank by the
enriched score/date. `read_thread` and `browse_subreddit` are unaffected.

Listings drop mod-removed / deleted posts. This matters because heavily
moderated subs (e.g. r/selfhosted) AutoMod-hold most *new* posts pending review,
so an unfiltered "newest" list would otherwise be a wall of
`[ Removed by moderator ]`.

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
