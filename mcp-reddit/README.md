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
SEARXNG_URL=http://localhost:8888 uv run --no-project --with mcp --with httpx python server.py
```

Ships as `ghcr.io/alxleo/mcp-reddit:latest` — mcp-proxy HTTP bridge on :8080 with `/ping`.
`SEARXNG_URL` defaults to `http://searxng:8080` (the homelab SearXNG on `mcp-network`).

## Search

Arctic-Shift's **server-side full-text index (the `query`/`title`/`selftext` filters)
is under maintenance and returns HTTP 503**, and Reddit's own API/JSON is closed — so
there is no credential-free native search. `search_reddit` instead runs a full-text
query through the self-hosted **SearXNG** (`site:reddit.com`, aggregating Google/Bing/…),
then enriches each hit with live score + comment counts from Arctic-Shift's `/posts/ids`
(that endpoint works; only Arctic-Shift's *search* index is down). This gives real
global, relevance-ranked Reddit search with zero credentials. `sort="top"`/`"new"` rerank
by the enriched score/date. If SearXNG is unreachable, `search_reddit` returns a clear
message; `read_thread` and `browse_subreddit` are unaffected.

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
