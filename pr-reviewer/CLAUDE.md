# PR Reviewer

AI-powered multi-model PR review with specialized lens agents. Runs as a Docker container receiving Gitea/GitHub webhooks.

## Architecture

**Orchestrator + sub-agents, not N separate calls.** One `claude -p` session spawns lens sub-agents via the Agent tool. This uses ~1/5th the rate limit of running each lens separately. Non-Claude models (Gemini, Codex) fall back to individual calls since they lack the Agent tool.

**Python routes, Claude reviews.** `analyze_diff_relevance()` pre-filters which lenses to run based on file types and content patterns (zero LLM cost). The orchestrator then spawns only relevant lens agents. Deep mode bypasses routing and runs all lenses.

**Three AI models, all subscription auth:**
- Claude: `CLAUDE_CODE_OAUTH_TOKEN` env var (Claude Max)
- Gemini: mounted `~/.gemini/oauth_creds.json` + `settings.json` (Google subscription)
- Codex: mounted `~/.codex/auth.json` (ChatGPT subscription)

No API keys. Container maps host `CC_TOKEN` → `CLAUDE_CODE_OAUTH_TOKEN` to avoid interfering with the user's own Claude sessions.

## Review Pipeline

```
Webhook received (push/pull_request/issue_comment)
  → Auto-create PR if none exists (push events)
  → Fetch diff, PR metadata, commit messages
  → Generate repomap (tree-sitter structural map)
  → Run impact analysis (rg -l per changed file)
  → Preprocess diff (strip delete-only files, language annotations, token budget)
  → Shuffle diff file ordering (breaks LLM positional bias)
  → Route to relevant lenses via analyze_diff_relevance()
  → Orchestrated claude -p session spawns lens sub-agents
  → Cap findings by severity (keep highest when at max_comments)
  → Clean up old bot comments (tag-based: <!-- pr-reviewer-bot:LENS -->)
  → Post review (inline comments or top-level fallback)
  → Post commit status (success/failure based on fail_on_severity)
```

## Lens Agents

Lenses are Claude Code agent definitions in `plugin/agents/*.md`. Each has frontmatter (name, description, model, tools) and a system prompt describing cognitive review moves — not project-specific checklists.

| Lens | Cognitive moves | When routed |
|------|----------------|-------------|
| **security** | Trace trust boundaries, follow secrets, invert access models, check symmetric pairs | Security patterns in diff, infra files |
| **simplification** | Invert justification, count call sites, flatten nesting, check configurability | Code file changes (.py/.js/.ts/.go/.rs) |
| **standards** | Find source of truth (CLAUDE.md), pattern-match against siblings, check escape hatches | Config/infra file changes |
| **drift** | Follow dependency chains, check generators, verify registries, test mirrors | New files, config changes |
| **architecture** | Read the map first, identify boundaries, check symmetric counterparts, test precedent | New files, infra changes |

## Design Decisions

### Why cognitive moves, not project-specific rules?
Lenses that say "check if x-common anchor exists" only work on one repo. Lenses that say "pattern-match against sibling files" work on any repo. The reviewer discovers project conventions at review time by reading CLAUDE.md and existing code.

### Why shuffle the diff?
LLMs have positional bias — they pay more attention to early content. Randomizing file order produces different attention patterns each review. BugBot (Cursor) does this on 2M+ PRs/month.

### Why preprocess the diff?
Delete-only files are noise for review (saves ~20-30% tokens on refactors). Language annotations help the LLM identify file types without inferring from extensions. Token budget prevents exceeding model context on large PRs.

### Why impact analysis?
`rg -l` per changed file finds references — "who calls this?" and "what imports this?" — at zero LLM cost. Injected as context so the reviewer knows the blast radius.

### Why repomap?
Tree-sitter extracts top-level definitions (classes, functions, signatures) into a compact structural map. Like reading a table of contents before a chapter — gives the LLM orientation before it reads the diff.

### Why the orchestrator pattern?
Running 5 × `claude -p` per review hits rate limits fast. One session that spawns sub-agents via the Agent tool uses ~1/5th the budget. Sub-agents share the repo checkout and session context.

### Why severity-prioritized capping?
When `max_comments` is hit, keep CRITICAL/HIGH findings and drop LOW. Previously capping was arbitrary (first N findings regardless of severity).

### Why comment cleanup tags?
Without cleanup, re-reviewing a PR accumulates stale bot comments. HTML tags (`<!-- pr-reviewer-bot:LENS -->`) identify old reviews for deletion before posting new ones.

## CLI Invocation

Every `claude -p` call is fully deterministic:
```
claude -p --model sonnet --output-format json --allowedTools "Read,Glob,Grep,Bash(git:*),Bash(sg:*),WebSearch,WebFetch,Agent" --max-turns 10 --plugin-dir /app/plugin
```

Never invoke `claude -p` bare. Always specify `--model`, `--allowedTools`, `--max-turns`, `--output-format`, `--plugin-dir`.

Gemini: `-p` requires prompt as string argument, not stdin. Use `-p "instruction"` with content on stdin.
Codex: `codex exec` works with OAuth. `codex exec review` doesn't (websocket API path).

## Configuration (reviewer-config.yml)

```yaml
auto_trigger: pr_open          # pr_open | every_commit | on_demand
auto_lenses: [simplification, security]
default_model: claude
shuffle_diff: true              # randomize file order to break positional bias

models:
  claude: sonnet               # auto/standard reviews
  claude_deep: opus            # deep reviews get the best model
  gemini: gemini-2.5-pro
  codex: o3

lenses:
  simplification: { enabled: true, max_comments: 5 }
  security: { enabled: true, max_comments: 5 }
  # Per-lens model override: security: { model: gemini }
```

## Commands (via PR comments on Gitea)

```
@pr-reviewer                      → auto lenses via default model
@pr-reviewer deep                 → all lenses, unlimited comments, opus model
@pr-reviewer quick                → simplification only, max 3 comments
@pr-reviewer security             → single lens
@pr-reviewer with gemini          → auto lenses via Gemini
@pr-reviewer deep with codex      → all lenses via Codex
@pr-reviewer stop                 → stop processing this PR
```

## Key Files

| File | Purpose |
|------|---------|
| `scripts/review_core.py` | Shared engine: prompts, lenses, routing, preprocessing, orchestration |
| `scripts/gitea_webhook.py` | Gitea webhook handler: events, PR creation, review dispatch, posting |
| `scripts/gh_watcher.py` | GitHub polling handler (older path, less feature-rich) |
| `scripts/sync_plugins.py` | Startup plugin sync from config |
| `scripts/entrypoint.py` | Container entrypoint: sync plugins then exec handler |
| `prompts/_preamble.md` | Shared review rules (anti-hallucination, tool usage, output format) |
| `prompts/*.md` | Lens prompt templates (used by build_review_prompt) |
| `plugin/agents/*.md` | Lens agent definitions (used by orchestrator via Agent tool) |
| `config.example.yml` | Configuration reference |

## Research & Provenance

Design informed by analysis of: PR-Agent (Qodo, 10K stars), ai-review (Filonov), TerraScan, Kodus. Key patterns adopted:

- **Anti-hallucination rules** — explicit instructions to verify before flagging (PR-Agent)
- **Diff preprocessing** — strip delete-only files, token budget compression (PR-Agent)
- **Impact analysis** — grep-based reference finding per changed file (TerraScan)
- **Severity-prioritized capping** — keep highest severity when at limit (TerraScan)
- **Shuffled diff ordering** — break positional bias (BugBot/Cursor)
- **Repomap** — tree-sitter structural overview (Aider/grep-ast)
- **Symmetric counterpart search** — check create/validate pairs (Kodus)

## Backlog

- **LLM-planned search queries** — separate LLM call generates ripgrep patterns from the diff (Kodus planner). Five categories: callers, symmetric counterparts, test pairs, config limits, upstream deps. The endgame for cross-file understanding.
- **code-index-mcp sidecar** — tree-sitter AST indexing as MCP tools for deeper symbol analysis
- **Suggestion blocks** — verify Gitea renders `` ```suggestion `` as apply buttons
- **Repomap + impact for gh_watcher.py** — GitHub polling path doesn't have these yet
