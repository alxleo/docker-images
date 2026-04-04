# PR Reviewer

AI-powered multi-model PR review with specialized lens agents. Runs as Docker containers — one for Gitea (webhook-driven), one for GitHub (polling, multi-org). Both deployed from local-cicd.

## Architecture

**Orchestrator + sub-agents, not N separate calls.** One `claude -p` session spawns lens sub-agents via the Agent tool. This uses ~1/5th the rate limit of running each lens separately. Non-Claude models (Gemini, Codex) fall back to individual calls since they lack the Agent tool.

**Python routes, Claude reviews.** `analyze_diff_relevance()` pre-filters which lenses to run based on file types and content patterns (zero LLM cost). The orchestrator then spawns only relevant lens agents. Deep mode bypasses routing and runs all lenses.

**Three AI models, all subscription auth:**
- Claude: `REVIEWER_CLAUDE_TOKEN` → file at `/run/secrets/reviewer_claude_token` → set as `CLAUDE_CODE_OAUTH_TOKEN` internally
- Gemini: mounted `~/.gemini/oauth_creds.json` + `settings.json` (Google subscription)
- Codex: mounted `~/.codex/auth.json` (ChatGPT subscription)

All secrets mounted as files at `/run/secrets/` (not env vars). `read_secret()` checks file → env var → uppercase env var.

**Read-only tools enforced.** Review agents get `Bash(git log:*)`, `Bash(git blame:*)`, `Bash(git diff:*)`, `Bash(git show:*)` — never `Bash(git:*)`. Test regression guard asserts `Edit`, `Write`, and unrestricted `Bash(git:*)` are NOT in the allowed tools.

## Deployment

Two containers in local-cicd, same image, different entrypoints:

| Container | Forge | Entrypoint | Config |
|-----------|-------|-----------|--------|
| `local-ci-reviewer-gitea` | Gitea webhooks | `gitea_webhook.py` | `reviewer-config.yml` |
| `local-ci-reviewer-github` | GitHub polling (multi-org) | `gh_watcher.py` | `reviewer-config-github.yml` |

GitHub container supports multiple orgs via `apps` config section — one GitHub App per org, token switched per-repo in the poll loop. All secrets mounted as files at `/run/secrets/` (not env vars).

**Default: on_demand.** Reviews only run when someone comments `@pr-reviewer` on a PR. Auto-PR creation and auto-review are opt-in via config (`auto_trigger`, `auto_create_pr`).

## Review Pipeline

```
Webhook/poll picks up @pr-reviewer command
  → React 👀 on command comment (immediate acknowledgement)
  → Fetch diff, PR metadata, commit messages
  → Resolve head_sha (fetch from PR API if missing)
  → Generate repomap (PageRank-ranked, diff-personalized, tree-sitter)
  → Run LLM-planned search (haiku generates ripgrep patterns, Python executes)
  → Preprocess diff (strip delete-only files, language annotations, token budget)
  → Shuffle diff file ordering (breaks LLM positional bias)
  → Route to relevant lenses via analyze_diff_relevance()
  → Post status comment ("⏳ Reviewing with X lens(es) via model...")
  → Orchestrated claude -p session spawns lens sub-agents
  → Per-lens severity cap (keep highest when at max_comments)
  → Parse findings into structured Finding objects (verification.py)
  → Verify each finding: diff presence, file/line existence, cross-file claims
  → Score all findings via haiku (0-10 on evidence/actionability/usefulness)
  → Apply total cross-lens comment cap (high-confidence findings exempt)
  → Post inline comments (verified) + body-only comments (downgraded)
  → Post review (via Reviews API — inline comments or body-only fallback)
  → Update status comment ("✅ Review complete — N lens reports (Xs)")
  → Post commit status (success/failure based on fail_on_severity)
```

## Code Structure

Decomposed into focused modules (each <200 lines):

| Module | Purpose |
|--------|---------|
| `config.py` | Paths, constants, secrets, state, lens selection, command parsing |
| `prompts.py` | Prompt assembly from `.md` templates |
| `models.py` | Claude/Gemini/Codex CLI invocation (deterministic). `ReviewResult` captures session metadata (turns, cost, tokens). |
| `routing.py` | Diff relevance analysis, lens dispatch to models |
| `orchestrator.py` | Single-session orchestration with sub-agents |
| `diff.py` | Diff preprocessing, shuffle |
| `context.py` | Repomap (PageRank-ranked, tree-sitter), LLM-planned searches |
| `output.py` | Inline comment parsing, severity capping |
| `verification.py` | Post-processing: parse findings, verify against code, haiku scoring, total cap, render |
| `review_core.py` | Thin re-export facade (backwards compat) |
| `gitea_webhook.py` | Gitea webhook handler: events, PR creation, review dispatch |
| `gh_watcher.py` | GitHub polling handler |
| `sync_plugins.py` | Startup plugin sync from config |
| `entrypoint.py` | Container entrypoint: sync plugins then exec handler |

Prompts are `.md` files — text, not Python. They change independently of logic:
- `prompts/_preamble.md` — shared review rules
- `prompts/_planner.md` — LLM-planned search instructions
- `prompts/*.md` — lens-specific cognitive moves
- `plugin/agents/*.md` — lens agent definitions with frontmatter

## Lens Agents

| Lens | Cognitive moves | When routed |
|------|----------------|-------------|
| **security** | Trace trust boundaries, follow secrets, invert access models, check symmetric pairs | Security patterns in diff, infra files |
| **simplification** | Invert justification, count call sites, flatten nesting, check configurability | Code file changes (.py/.js/.ts/.go/.rs) |
| **standards** | Find source of truth (CLAUDE.md), pattern-match against siblings, check escape hatches | Config/infra file changes |
| **drift** | Follow dependency chains, check generators, verify registries, test mirrors | New files, config changes |
| **architecture** | Read the map first, identify boundaries, check symmetric counterparts, test precedent | New files, infra changes |

## CLI Invocation

Every `claude -p` call is fully deterministic:
```
claude -p --model sonnet --output-format json \
  --allowedTools "Read,Glob,Grep,Bash(git log:*),Bash(git blame:*),Bash(git diff:*),Bash(git show:*),Bash(sg:*),WebSearch,WebFetch,Agent" \
  --max-turns 10 --plugin-dir /app/plugin
```

Never invoke `claude -p` bare. Always specify `--model`, `--allowedTools`, `--max-turns`, `--output-format`, `--plugin-dir`.

Timeout scales with max_turns: 60s per turn, minimum 300s.

**Gemini:** `-p` requires prompt as string argument, not stdin. Use `-p "instruction"` with content on stdin.
**Codex:** `codex exec` works with OAuth. `codex exec review` doesn't (websocket API path).

## Configuration

```yaml
auto_trigger: on_demand        # on_demand | pr_open | every_commit
auto_create_pr: false          # don't auto-create PRs on branch push
auto_lenses: [simplification, security]
default_model: claude
shuffle_diff: true
planned_searches: true         # LLM-planned cross-file search (haiku)

models:
  claude: sonnet
  claude_deep: opus
  gemini: gemini-2.5-pro
  codex: o3

lenses:
  simplification: { enabled: true, max_comments: 5 }
  security: { enabled: true, max_comments: 5 }
  # Per-lens model override: security: { model: gemini }

# Post-processing (all optional — defaults apply if absent)
scoring_enabled: true           # haiku scores each finding 0-10 (~$0.001/review)
scoring_threshold: 6            # drop findings below this score
max_total_comments: 7           # cross-lens total cap (0 = unlimited)
scoring_exempt_threshold: 9     # findings >= this bypass total cap
```

**Post-processing pipeline:** After lenses produce findings, `verification.py` runs a three-stage pipeline: (1) verify each finding against the actual checkout (file exists, line in diff, cross-file claims spot-checked), (2) score all findings via haiku for evidence/actionability/usefulness, (3) apply total cap across lenses (high-confidence findings exempt). Unverified findings are downgraded to body-only comments (not inline). All decisions logged at INFO.

## Commands (via PR comments on Gitea or GitHub)

```
@pr-reviewer                      → auto lenses via default model
@pr-reviewer deep                 → all lenses, unlimited comments, opus model
@pr-reviewer quick                → simplification only, max 3 comments
@pr-reviewer security             → single lens
@pr-reviewer with gemini          → auto lenses via Gemini
@pr-reviewer deep with codex      → all lenses via Codex
@pr-reviewer stop                 → stop processing this PR
```

## Gotchas

- **on_demand is the default.** Auto-PR creation and auto-review are off. Every branch push was triggering reviews before this was fixed.
- **Planner (haiku) may timeout** — gracefully degrades, review continues without cross-file context.
- **GitHub poller retry loop** — if a review fails, the comment must be marked as processed to prevent infinite re-dispatch. Fixed with try/except in `check_comments`.
- **Home-network prompt volume mount** overrides baked-in prompts. If deploying with a mount, keep prompts in sync. The local-cicd deployment uses baked-in prompts (no mount).
- **Gemini CLI `-p` flag** requires prompt as string argument, not stdin.
- **Codex `exec review` broken** with mounted OAuth creds (websocket path). Use `codex exec`.
- **Git clone in container** needs token in URL. Gitea repos require auth even for clone.

## Backlog

See [docker-images#76](https://github.com/alxleo/docker-images/issues/76) for future work:
- Prompt adherence for inline `[file:line]` format
- Dependency graph awareness, test coverage mapping
- Model routing by lens, consensus mode, cost budgets
- Cost dashboard, quality metrics, session replay
