#!/usr/bin/env python3
"""Poll GitHub for PR events and dispatch AI reviews.

Watches allowlisted private repos for:
- @pr-reviewer commands in PR comments → on-demand review
- @pr-reviewer stop → stops processing for a PR

Auth: GitHub App (installation token, auto-rotates hourly).
"""

import json
import logging
import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import review_core as core

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gh-watcher")


# ---------------------------------------------------------------------------
# GitHub App auth
# ---------------------------------------------------------------------------


class GitHubAppAuth:
    """Manages GitHub App JWT → installation token lifecycle."""

    def __init__(self, app_id: int, installation_id: int, private_key: str):
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key = private_key
        self._token: str | None = None
        self._expires_at: float = 0

    def get_token(self) -> str:
        """Return cached installation token, refreshing if expired."""
        if self._token and time.time() < self._expires_at - 300:  # 5min buffer
            return self._token
        self._refresh()
        if self._token is None:
            raise RuntimeError("Failed to obtain GitHub App installation token")
        return self._token

    def _refresh(self):
        """Generate JWT, exchange for 1-hour installation token."""
        import jwt  # PyJWT

        now = int(time.time())
        payload = {"iss": str(self.app_id), "iat": now - 60, "exp": now + 600}
        jwt_token = jwt.encode(payload, self.private_key, algorithm="RS256")

        url = f"https://api.github.com/app/installations/{self.installation_id}/access_tokens"
        req = urllib.request.Request(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pr-reviewer-gh-watcher",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            resp = json.loads(response.read())
        self._token = resp["token"]
        expires_str = resp["expires_at"].replace("Z", "+00:00")
        self._expires_at = datetime.fromisoformat(expires_str).timestamp()
        log.info("GitHub App token refreshed, expires at %s", resp["expires_at"])


def setup_auth() -> GitHubAppAuth:
    """Configure authentication from secrets. Returns GitHub App auth manager."""
    claude_token = core.read_secret("claude_code_oauth_token")
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token

    # GitHub App auth — installation tokens rotate hourly
    app_id = core.read_secret("gh_app_id")
    installation_id = core.read_secret("gh_app_installation_id")
    private_key = core.read_secret("gh_app_private_key")
    app_auth = GitHubAppAuth(int(app_id), int(installation_id), private_key)

    # Set initial token so gh CLI works immediately
    os.environ["GH_TOKEN"] = app_auth.get_token()

    # Optional: Gemini and Codex for multi-model review
    gemini_key = core.read_secret("gemini_api_key", required=False)
    openai_key = core.read_secret("openai_api_key", required=False)
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
    if openai_key:
        os.environ["OPENAI_API_KEY"] = openai_key

    models = ["claude"]
    if gemini_key:
        models.append("gemini")
    if openai_key:
        models.append("codex")
    log.info("Auth configured: %s + GitHub App", " + ".join(models))

    return app_auth


# ---------------------------------------------------------------------------
# GitHub CLI helpers
# ---------------------------------------------------------------------------


def gh(args: list[str], repo: str | None = None) -> str:
    """Run a gh CLI command and return stdout."""
    cmd = ["gh"]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error("gh %s failed: %s", " ".join(args), result.stderr.strip())
        return ""
    return result.stdout


def gh_json(args: list[str], repo: str | None = None) -> list | dict:
    """Run a gh CLI command and parse JSON output."""
    output = gh(args, repo)
    if not output:
        return []
    return json.loads(output)


STATUS_TAG = "<!-- pr-reviewer-status -->"


# ---------------------------------------------------------------------------
# GitHub-specific repo/PR operations
# ---------------------------------------------------------------------------


def save_poll_timestamp():
    """Write last poll time for healthcheck."""
    ts_file = core.STATE_DIR / "last_poll.json"
    core.STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts_file.write_text(json.dumps({"last_poll": time.time()}))


def clone_or_update(repo: str) -> Path:
    """Clone repo or pull latest. Returns repo directory."""
    safe_name = repo.replace("/", "_")
    repo_dir = core.REPOS_DIR / safe_name
    if repo_dir.exists():
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=repo_dir,
            capture_output=True,
            timeout=120,
        )
    else:
        core.REPOS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["gh", "repo", "clone", repo, str(repo_dir), "--", "--depth=50"],
            capture_output=True,
            timeout=120,
        )
    return repo_dir


def checkout_pr(repo_dir: Path, pr_number: int):
    """Checkout the PR branch in the cloned repo."""
    subprocess.run(
        ["gh", "pr", "checkout", str(pr_number), "--force"],
        cwd=repo_dir,
        capture_output=True,
        timeout=60,
    )


def get_diff(repo: str, pr_number: int) -> str:
    """Get the PR diff via gh."""
    return gh(["pr", "diff", str(pr_number)], repo=repo)


def get_head_sha(repo: str, pr_number: int) -> str:
    """Get the current head SHA of a PR."""
    pr_data = gh_json(["pr", "view", str(pr_number), "--json", "headRefOid"], repo=repo)
    if isinstance(pr_data, dict):
        return pr_data.get("headRefOid", "")
    return ""


def post_inline_review(repo: str, pr_number: int, lens_name: str, comments: list[dict], head_sha: str) -> bool:
    """Post inline review comments via GitHub API. Returns True on success."""
    icon = core.LENS_ICONS.get(lens_name, "\U0001f50d")
    review_body = f"{icon} **{lens_name.title()} Review** — {len(comments)} finding(s)"

    payload = json.dumps({
        "commit_id": head_sha,
        "body": review_body,
        "event": "COMMENT",
        "comments": [
            {"path": c["path"], "line": c["line"], "body": c["body"]}
            for c in comments
        ],
    })

    cmd = [
        "gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews",
        "--method", "POST",
        "--input", "-",
    ]
    result = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        log.error("Failed to post inline review for PR #%d: %s", pr_number, result.stderr)
        return False
    log.info("Posted %d inline %s comments on %s#%d", len(comments), lens_name, repo, pr_number)
    return True


def post_review(repo: str, pr_number: int, lens_name: str, body: str, diff: str = ""):
    """Post review on PR — inline comments if possible, top-level comment as fallback."""
    icon = core.LENS_ICONS.get(lens_name, "\U0001f50d")

    # Try inline comments if we have the diff
    if diff:
        comments = core.parse_inline_comments(body, diff)
        if comments:
            head_sha = get_head_sha(repo, pr_number)
            if head_sha and post_inline_review(repo, pr_number, lens_name, comments, head_sha):
                return

    # Fallback: top-level PR comment
    header = f"## {icon} {lens_name.title()} Review\n\n"
    full_body = header + body

    cmd = ["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body-file", "-"]
    result = subprocess.run(cmd, input=full_body, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        log.error("Failed to post review for PR #%d lens %s: %s", pr_number, lens_name, result.stderr)
    else:
        log.info("Posted %s review on %s#%d", lens_name, repo, pr_number)


def react_eyes(repo: str, comment_id: str):
    """Add 👀 reaction to a comment — immediate "I saw it" signal."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/comments/{comment_id}/reactions",
         "--method", "POST", "-f", "content=eyes"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        log.info("Reacted 👀 on %s comment %s", repo, comment_id)
    else:
        log.debug("Reaction failed — non-critical: %s", result.stderr.strip()[:100])


def post_status_comment(repo: str, pr_number: int, message: str):
    """Post or update a status comment on a PR."""
    body = message + "\n\n" + STATUS_TAG

    # Look for existing status comment to edit via REST API
    comments_json = gh_json(
        ["api", f"repos/{repo}/issues/{pr_number}/comments", "--paginate",
         "--jq", f'[.[] | select(.body | contains("{STATUS_TAG}")) | .id] | first'],
    )
    existing_id = None
    if isinstance(comments_json, (int, float)):
        existing_id = int(comments_json)

    if existing_id:
        payload = json.dumps({"body": body})
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/comments/{existing_id}",
             "--method", "PATCH", "--input", "-"],
            input=payload, capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            log.info("Updated status comment on %s#%d", repo, pr_number)
            return

    # Create new comment
    cmd = ["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body-file", "-"]
    result = subprocess.run(cmd, input=body, capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        log.info("Posted status comment on %s#%d", repo, pr_number)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def dispatch_review(config: dict, repo: str, pr_number: int, depth: str,
                    model_override: str | None = None):
    """Run all enabled lenses against a PR and post results."""
    log.info("Reviewing %s#%d at depth=%s", repo, pr_number, depth)
    start_time = time.time()

    repo_dir = clone_or_update(repo)
    checkout_pr(repo_dir, pr_number)
    diff = get_diff(repo, pr_number)

    if not diff:
        log.warning("Empty diff for %s#%d, skipping", repo, pr_number)
        return

    # Fetch PR metadata for context
    pr_description = ""
    commit_messages = ""
    pr_data = gh_json(["pr", "view", str(pr_number), "--json", "body,commits"], repo=repo)
    if isinstance(pr_data, dict):
        pr_description = pr_data.get("body", "") or ""
        commits = pr_data.get("commits", [])
        if commits:
            commit_messages = "\n".join(
                f"- {c.get('messageHeadline', '')}" for c in commits
            )

    # Generate structural map + impact analysis
    repomap = core.generate_repomap(repo_dir)
    if repomap:
        log.info("Repomap: %d chars", len(repomap))
    impact = core.analyze_impact(repo_dir, diff)
    if impact:
        log.info("Impact: %d references found", impact.count("referenced by"))

    cross_file_context = core.plan_searches(diff, repo_dir, config)
    if cross_file_context:
        log.info("Planned searches: %d chars of cross-file context", len(cross_file_context))

    all_lenses = core.enabled_lenses(config, depth)

    # Intelligent routing: for auto/standard depth, only run relevant lenses
    if depth in ("auto", "standard"):
        relevant = core.analyze_diff_relevance(diff)
        lenses = [l for l in all_lenses if l["name"] in relevant]
        if len(lenses) < len(all_lenses):
            skipped = [l["name"] for l in all_lenses if l["name"] not in relevant]
            log.info("Routing: %d/%d lenses relevant (skipping: %s)",
                     len(lenses), len(all_lenses), ", ".join(skipped))
    else:
        lenses = all_lenses

    # Post status comment — "Reviewing with X lens(es)..."
    model_name = model_override or config.get("default_model", "claude")
    lens_list = ", ".join(l["name"] for l in lenses)
    status_msg = f"\u23f3 **Reviewing** with {lens_list} lens(es) via `{model_name}`..."
    post_status_comment(repo, pr_number, status_msg)

    # Orchestrated review (single Claude session with sub-agents)
    review_results = core.run_review_orchestrated(
        lenses, diff, repo_dir, config,
        commit_messages=commit_messages,
        pr_description=pr_description,
        model_override=model_override,
        repomap=repomap, depth=depth, impact=impact,
        cross_file_context=cross_file_context,
    )

    for lens_name, result in review_results:
        lens_cfg = next((l for l in lenses if l["name"] == lens_name), None)
        # Orchestrated "review" results aggregate multiple lenses — use deep_overrides cap (default: unlimited)
        max_comments = lens_cfg["max_comments"] if lens_cfg else config.get("deep_overrides", {}).get("max_comments", 0)
        result = core.cap_by_severity(result, max_comments)
        post_review(repo, pr_number, lens_name, result, diff=diff)

    # Update status comment — done
    elapsed = int(time.time() - start_time)
    posted = len(review_results)
    done_msg = f"\u2705 **Review complete** — {posted} lens report(s) from {lens_list} via `{model_name}` ({elapsed}s)"
    post_status_comment(repo, pr_number, done_msg)

    # Update state — reload from disk to avoid clobbering concurrent writes
    state = core.load_state(repo, pr_number)
    state["last_reviewed_at"] = time.time()
    state["last_head_sha"] = get_head_sha(repo, pr_number)
    core.save_state(repo, pr_number, state)


def check_comments(config: dict, repo: str, pr_number: int, comments: list):
    """Check PR comments for @review commands."""
    state = core.load_state(repo, pr_number)
    processed_ids = set(state.get("processed_comment_ids", []))

    for comment in comments:
        comment_id = str(comment.get("id", ""))
        if comment_id in processed_ids:
            continue

        body = comment.get("body", "")
        parsed = core.parse_command(body)
        if parsed is None:
            continue
        depth, model_override = parsed

        processed_ids.add(comment_id)

        # Immediate feedback: react with 👀 (best-effort, never blocks dispatch)
        try:
            react_eyes(repo, comment_id)
        except Exception:
            log.debug("Failed to add 👀 reaction for comment %s — non-critical", comment_id)

        if depth == "stop":
            log.info("Stop command received for %s#%d", repo, pr_number)
        else:
            try:
                dispatch_review(config, repo, pr_number, depth, model_override)
            except Exception:
                log.exception("Review failed for %s#%d (comment %s) — marking processed to avoid retry loop",
                              repo, pr_number, comment_id)
                post_status_comment(repo, pr_number,
                                    "\u274c **Review failed** — check container logs for details")

    # Reload state after dispatch_review may have updated it on disk,
    # then merge in our processed_comment_ids to avoid clobbering
    state = core.load_state(repo, pr_number)
    state["processed_comment_ids"] = list(processed_ids)
    core.save_state(repo, pr_number, state)


def poll(config: dict):
    """Single poll cycle across all configured repos."""
    owner = config.get("owner_filter", "")

    for repo in config.get("repos", []):
        # Verify repo ownership
        if owner and not repo.startswith(f"{owner}/"):
            log.warning("Repo %s doesn't match owner filter %s, skipping", repo, owner)
            continue

        try:
            prs = gh_json(
                ["pr", "list", "--state", "open", "--json", "number,updatedAt,isDraft,headRefOid,comments"],
                repo=repo,
            )
        except Exception as e:
            log.error("Failed to list PRs for %s: %s", repo, e)
            continue

        if not isinstance(prs, list):
            continue

        for pr in prs:
            pr_number = pr.get("number")
            if not pr_number:
                continue

            is_draft = pr.get("isDraft", False)
            if is_draft and config.get("skip_drafts", True):
                log.debug("Skipping draft PR %s#%d", repo, pr_number)
                continue

            # Check for @pr-reviewer commands in comments (on-demand only)
            comments = pr.get("comments", [])
            if comments:
                check_comments(config, repo, pr_number, comments)

    save_poll_timestamp()


def main():
    log.info("PR Reviewer starting")

    config = core.load_config()
    app_auth = setup_auth()

    log.info(
        "Watching %d repos, polling every %ds (on-demand only)",
        len(config.get("repos", [])),
        config.get("polling_interval", 60),
    )

    interval = config.get("polling_interval", 60)

    while True:
        try:
            # Refresh GitHub App token (auto-rotates hourly, cached otherwise)
            os.environ["GH_TOKEN"] = app_auth.get_token()
            poll(config)
        except Exception:
            log.exception("Poll cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
