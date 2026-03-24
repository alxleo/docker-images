#!/usr/bin/env python3
"""Gitea webhook handler — auto-review PRs on push/open/comment.

Receives Gitea webhook POSTs and dispatches AI reviews:
- push → auto-create PR if none exists for the branch
- pull_request (opened/synchronized) → auto-review with configured lenses
- issue_comment on PRs → parse @pr-reviewer commands, dispatch on-demand

Auth: Gitea API token (GITEA_TOKEN env var).
"""

import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

import review_core as core

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gitea-webhook")

# Thread pool for background review dispatch — webhook returns 200 immediately
_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------

GITEA_URL = os.environ.get("GITEA_URL", "http://local-ci-gitea:3000")
GITEA_ORG = os.environ.get("GITEA_ORG", "ci")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
LISTEN_PORT = int(os.environ.get("PORT", "8000"))


def gitea_client() -> httpx.Client:
    """Create an httpx client with Gitea token auth."""
    token = os.environ.get("GITEA_TOKEN", "")
    return httpx.Client(
        base_url=f"{GITEA_URL}/api/v1",
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Gitea API operations
# ---------------------------------------------------------------------------


def get_diff(client: httpx.Client, owner: str, repo: str, pr_number: int) -> str:
    """Get PR diff from Gitea API."""
    r = client.get(
        f"/repos/{owner}/{repo}/pulls/{pr_number}.diff",
        headers={"Accept": "text/plain"},
    )
    if r.status_code != 200:
        log.error("Failed to get diff for %s/%s#%d: %d", owner, repo, pr_number, r.status_code)
        return ""
    return r.text


def _authenticated_url(owner: str, repo: str) -> str:
    """Build a git clone URL with token auth embedded."""
    token = os.environ.get("GITEA_TOKEN", "")
    # Insert token into URL: http://token@host:port/owner/repo.git
    url = GITEA_URL.replace("://", f"://token:{token}@") if token else GITEA_URL
    return f"{url}/{owner}/{repo}.git"


def clone_or_update(owner: str, repo: str) -> Path:
    """Clone repo from Gitea or fetch latest. Returns repo directory."""
    safe_name = f"{owner}_{repo}"
    repo_dir = core.REPOS_DIR / safe_name
    clone_url = _authenticated_url(owner, repo)
    if repo_dir.exists():
        # Update remote URL in case token changed
        subprocess.run(
            ["git", "remote", "set-url", "origin", clone_url],
            cwd=repo_dir, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=repo_dir, capture_output=True, timeout=120,
        )
    else:
        core.REPOS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=50", clone_url, str(repo_dir)],
            capture_output=True, timeout=120,
        )
    return repo_dir


def checkout_branch(repo_dir: Path, branch: str):
    """Checkout a specific branch in the cloned repo."""
    subprocess.run(
        ["git", "checkout", "-f", branch],
        cwd=repo_dir,
        capture_output=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "pull", "--ff-only", "origin", branch],
        cwd=repo_dir,
        capture_output=True,
        timeout=60,
    )


BOT_TAG = "<!-- pr-reviewer-bot:{lens} -->"

# Severity threshold for CI gating (commit status)
_FAIL_SEVERITIES = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def post_commit_status(client: httpx.Client, owner: str, repo: str, sha: str,
                       state: str, description: str):
    """Post a commit status to Gitea (success/failure/pending)."""
    r = client.post(f"/repos/{owner}/{repo}/statuses/{sha}", json={
        "state": state,
        "description": description[:140],
        "context": "pr-reviewer",
        "target_url": "",
    })
    if r.status_code in (200, 201):
        log.info("Commit status: %s on %s/%s@%s — %s", state, owner, repo, sha[:8], description)
    else:
        log.warning("Failed to post commit status: %d", r.status_code)


def cleanup_old_reviews(client: httpx.Client, owner: str, repo: str, pr_number: int,
                        lens_name: str):
    """Delete old bot review comments for this lens before posting new ones."""
    tag = BOT_TAG.format(lens=lens_name)
    r = client.get(f"/repos/{owner}/{repo}/issues/{pr_number}/comments", params={"limit": 50})
    if r.status_code != 200:
        return
    deleted = 0
    for comment in r.json():
        if tag in comment.get("body", ""):
            client.delete(f"/repos/{owner}/{repo}/issues/comments/{comment['id']}")
            deleted += 1
    # Also clean up inline reviews
    r = client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")
    if r.status_code == 200:
        for review in r.json():
            if tag in review.get("body", ""):
                client.delete(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review['id']}")
                deleted += 1
    if deleted:
        log.info("Cleaned up %d old %s review(s) on %s/%s#%d", deleted, lens_name, owner, repo, pr_number)


def post_review(client: httpx.Client, owner: str, repo: str, pr_number: int,
                lens_name: str, body: str, head_sha: str, diff: str = ""):
    """Post review on a Gitea PR — inline comments if possible, fallback to top-level."""
    icon = core.LENS_ICONS.get(lens_name, "\U0001f50d")
    tag = BOT_TAG.format(lens=lens_name)

    # Clean up previous bot reviews for this lens
    cleanup_old_reviews(client, owner, repo, pr_number, lens_name)

    # Try inline review via Gitea's review API
    if diff:
        comments = core.parse_inline_comments(body, diff)
        if comments and head_sha:
            review_body = f"{icon} **{lens_name.title()} Review** — {len(comments)} finding(s)\n{tag}"
            payload = {
                "commit_id": head_sha,
                "body": review_body,
                "event": "COMMENT",
                "comments": [
                    {"path": c["path"], "new_position": c["line"], "body": c["body"]}
                    for c in comments
                ],
            }
            r = client.post(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", json=payload)
            if r.status_code in (200, 201):
                log.info("Posted %d inline %s comments on %s/%s#%d",
                         len(comments), lens_name, owner, repo, pr_number)
                return
            log.warning("Inline review failed (%d), falling back to comment", r.status_code)

    # Fallback: top-level issue comment
    header = f"## {icon} {lens_name.title()} Review\n\n"
    full_body = header + body + f"\n\n{tag}"
    r = client.post(
        f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
        json={"body": full_body},
    )
    if r.status_code in (200, 201):
        log.info("Posted %s review comment on %s/%s#%d", lens_name, owner, repo, pr_number)
    else:
        log.error("Failed to post review on %s/%s#%d: %d %s",
                  owner, repo, pr_number, r.status_code, r.text[:200])


def ensure_pr(client: httpx.Client, owner: str, repo: str, branch: str) -> int | None:
    """Check if a PR exists for this branch; create one if not. Returns PR number or None."""
    # Check for existing open PR
    r = client.get(f"/repos/{owner}/{repo}/pulls", params={"state": "open", "limit": 50})
    if r.status_code == 200:
        for pr in r.json():
            if pr.get("head", {}).get("ref") == branch:
                log.info("PR already exists for %s/%s branch %s: #%d", owner, repo, branch, pr["number"])
                return pr["number"]

    # Create new PR
    title = branch.replace("-", " ").replace("_", " ").replace("/", ": ")
    r = client.post(f"/repos/{owner}/{repo}/pulls", json={
        "title": title,
        "head": branch,
        "base": "main",
        "body": f"Auto-created by pr-reviewer for branch `{branch}`.",
    })
    if r.status_code in (200, 201):
        pr_number = r.json()["number"]
        log.info("Created PR #%d for %s/%s branch %s", pr_number, owner, repo, branch)
        return pr_number
    log.error("Failed to create PR for %s/%s branch %s: %d %s",
              owner, repo, branch, r.status_code, r.text[:200])
    return None


# ---------------------------------------------------------------------------
# Review dispatch
# ---------------------------------------------------------------------------


def dispatch_review(config: dict, owner: str, repo: str, pr_number: int,
                    head_sha: str, depth: str, model_override: str | None = None):
    """Run enabled lenses against a PR and post results."""
    try:
        _dispatch_review_inner(config, owner, repo, pr_number, head_sha, depth, model_override)
    except Exception:
        log.exception("Review failed for %s/%s#%d", owner, repo, pr_number)


def _dispatch_review_inner(config: dict, owner: str, repo: str, pr_number: int,
                           head_sha: str, depth: str, model_override: str | None = None):
    log.info("Reviewing %s/%s#%d at depth=%s", owner, repo, pr_number, depth)

    with gitea_client() as client:
        # Fetch PR metadata once — used for head_sha, description, and context
        pr_description = ""
        pr_data = {}
        r = client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        if r.status_code == 200:
            pr_data = r.json()
            pr_description = pr_data.get("body", "") or ""
            if not head_sha:
                head_sha = pr_data.get("head", {}).get("sha", "")
                log.info("Resolved head_sha from PR API: %s", head_sha[:8] if head_sha else "empty")

        diff = get_diff(client, owner, repo, pr_number)
        if not diff:
            log.warning("Empty diff for %s/%s#%d, skipping", owner, repo, pr_number)
            return

        commit_messages = ""
        # Get commit messages for this PR
        r = client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}/commits")
        if r.status_code == 200:
            commits = r.json()
            commit_messages = "\n".join(
                f"- {c.get('commit', {}).get('message', '').split(chr(10))[0]}"
                for c in commits
            )

        repo_dir = clone_or_update(owner, repo)
        # Try fetching PR ref; fall back to just using the repo as-is
        fetch = subprocess.run(
            ["git", "fetch", "origin", f"pull/{pr_number}/head:pr/{pr_number}/head"],
            cwd=repo_dir, capture_output=True, timeout=60,
        )
        if fetch.returncode == 0:
            subprocess.run(
                ["git", "checkout", "-f", f"pr/{pr_number}/head"],
                cwd=repo_dir, capture_output=True, timeout=60,
            )

        # Generate structural map + impact analysis for context
        repomap = core.generate_repomap(repo_dir)
        if repomap:
            log.info("Repomap: %d chars", len(repomap))
        impact = core.analyze_impact(repo_dir, diff)
        if impact:
            log.info("Impact: %d references found", impact.count("referenced by"))

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
            lenses = all_lenses  # deep/quick/single-lens: run what was requested

        diff_lines = len(diff.splitlines())
        log.info("Diff: %d lines, %d lenses to run%s",
                 diff_lines, len(lenses),
                 f" (model override: {model_override})" if model_override else "")

        # Clean up old bot reviews for all lenses being run
        for lens in lenses:
            cleanup_old_reviews(client, owner, repo, pr_number, lens["name"])
        # Also clean up the "review" tag from orchestrated reviews
        cleanup_old_reviews(client, owner, repo, pr_number, "review")

        # Use orchestrated review (single Claude session with sub-agents)
        review_results = core.run_review_orchestrated(
            lenses, diff, repo_dir, config,
            commit_messages=commit_messages,
            pr_description=pr_description,
            model_override=model_override,
            repomap=repomap, depth=depth, impact=impact,
        )

        posted = 0
        all_results: list[str] = []
        for lens_name, result in review_results:
            # Use per-lens max_comments for cap; default to deep_overrides for orchestrated
            lens_cfg = next((l for l in lenses if l["name"] == lens_name), None)
            max_comments = lens_cfg["max_comments"] if lens_cfg else config.get("deep_overrides", {}).get("max_comments", 0)
            result = core.cap_by_severity(result, max_comments)
            all_results.append(result)
            post_review(client, owner, repo, pr_number,
                        lens_name, result, head_sha, diff=diff)
            posted += 1

        log.info("Review complete for %s/%s#%d: %d result(s) posted from %d lenses",
                 owner, repo, pr_number, posted, len(lenses))

        # CI gating: post commit status based on findings
        fail_on = config.get("fail_on_severity", "")
        if fail_on and head_sha:
            # Check if any finding at or above the threshold exists
            threshold = _FAIL_SEVERITIES.get(fail_on.upper(), 99)
            combined = "\n".join(all_results)
            found_severities = re.findall(r'###\s+\[(CRITICAL|HIGH|MEDIUM|LOW)\]', combined)
            worst = min((_FAIL_SEVERITIES[s] for s in found_severities), default=99)
            if worst <= threshold:
                worst_name = next(k for k, v in _FAIL_SEVERITIES.items() if v == worst)
                post_commit_status(client, owner, repo, head_sha, "failure",
                                   f"Review found {worst_name} issue(s)")
            else:
                post_commit_status(client, owner, repo, head_sha, "success",
                                   f"Review passed ({posted} findings, none above {fail_on})"
                                   if posted else "Review passed (no findings)")
        elif head_sha:
            # No gating configured — always post success
            post_commit_status(client, owner, repo, head_sha, "success",
                               f"Review complete ({posted} findings)" if posted else "Review passed")

    # Update state — reload from disk to avoid clobbering concurrent comment tracking
    state_key = f"{owner}/{repo}"
    state = core.load_state(state_key, pr_number)
    state["last_reviewed_at"] = time.time()
    state["last_head_sha"] = head_sha
    core.save_state(state_key, pr_number, state)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def handle_push(config: dict, payload: dict):
    """Auto-create PR for branch pushes (skip main)."""
    ref = payload.get("ref", "")
    if not ref.startswith("refs/heads/"):
        return
    branch = ref.removeprefix("refs/heads/")
    if branch == "main":
        return

    repo_info = payload.get("repository", {})
    owner = repo_info.get("owner", {}).get("login", GITEA_ORG)
    repo = repo_info.get("name", "")
    if not repo:
        return

    log.info("Push to %s/%s branch %s — checking for PR", owner, repo, branch)
    with gitea_client() as client:
        pr_number = ensure_pr(client, owner, repo, branch)
    # If PR was just created, Gitea fires a pull_request webhook → review happens there.
    # If PR already existed, the push also fires a pull_request synchronized event.
    if pr_number:
        log.info("PR #%d exists for %s/%s branch %s", pr_number, owner, repo, branch)


def handle_pull_request(config: dict, payload: dict):
    """Auto-review on PR events, controlled by auto_trigger config.

    Trigger modes (config.auto_trigger):
        pr_open       — review only when PR is first opened
        every_commit  — review on open + every push (default)
        on_demand     — never auto-review, only via @pr-reviewer commands
    """
    action = payload.get("action", "")
    trigger = config.get("auto_trigger", "every_commit")

    if trigger == "on_demand":
        return
    if trigger == "pr_open" and action != "opened":
        return
    if action not in ("opened", "synchronized"):
        return

    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    if not pr_number:
        return

    repo_info = payload.get("repository", {})
    owner = repo_info.get("owner", {}).get("login", GITEA_ORG)
    repo = repo_info.get("name", "")
    head_sha = pr.get("head", {}).get("sha", "")

    # Skip if we already reviewed this SHA
    state = core.load_state(f"{owner}/{repo}", pr_number)
    if state.get("last_head_sha") == head_sha:
        log.info("Already reviewed %s/%s#%d at %s, skipping", owner, repo, pr_number, head_sha[:8])
        return

    depth = "auto"

    log.info("Auto-reviewing %s/%s#%d (action=%s, sha=%s)", owner, repo, pr_number, action, head_sha[:8])
    _executor.submit(dispatch_review, config, owner, repo, pr_number, head_sha, depth)


def handle_issue_comment(config: dict, payload: dict):
    """Handle @pr-reviewer commands in PR comments."""
    issue = payload.get("issue", {})
    # Only process comments on pull requests
    if not issue.get("pull_request"):
        return

    comment = payload.get("comment", {})
    body = comment.get("body", "")
    parsed = core.parse_command(body)
    if parsed is None:
        return
    depth, model_override = parsed

    pr_number = issue.get("number")
    if not pr_number:
        return

    repo_info = payload.get("repository", {})
    owner = repo_info.get("owner", {}).get("login", GITEA_ORG)
    repo = repo_info.get("name", "")

    # Track processed comment IDs to avoid re-dispatch
    comment_id = str(comment.get("id", ""))
    state = core.load_state(f"{owner}/{repo}", pr_number)
    processed_ids = set(state.get("processed_comment_ids", []))
    if comment_id in processed_ids:
        return
    processed_ids.add(comment_id)
    state["processed_comment_ids"] = list(processed_ids)
    core.save_state(f"{owner}/{repo}", pr_number, state)

    if depth == "stop":
        log.info("Stop command received for %s/%s#%d", owner, repo, pr_number)
        return

    head_sha = issue.get("pull_request", {}).get("head", {}).get("sha", "")
    model_str = f" via {model_override}" if model_override else ""
    log.info("On-demand review %s/%s#%d depth=%s%s", owner, repo, pr_number, depth, model_str)
    _executor.submit(dispatch_review, config, owner, repo, pr_number, head_sha, depth, model_override)


# ---------------------------------------------------------------------------
# Webhook HTTP server
# ---------------------------------------------------------------------------


def verify_signature(body: bytes, signature: str) -> bool:
    """Verify Gitea webhook HMAC-SHA256 signature."""
    if not WEBHOOK_SECRET:
        return True  # no secret configured — skip validation
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class WebhookHandler(BaseHTTPRequestHandler):
    config: dict = {}

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Validate signature
        signature = self.headers.get("X-Gitea-Signature", "")
        if not verify_signature(body, signature):
            log.warning("Invalid webhook signature")
            self.send_response(401)
            self.end_headers()
            return

        # Parse event
        event = self.headers.get("X-Gitea-Event", "")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        # Return 200 immediately, dispatch in background
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

        # Route to handler
        if event == "push":
            _executor.submit(handle_push, self.config, payload)
        elif event == "pull_request":
            _executor.submit(handle_pull_request, self.config, payload)
        elif event == "issue_comment":
            _executor.submit(handle_issue_comment, self.config, payload)
        else:
            log.debug("Ignoring event: %s", event)

    def log_message(self, format, *args):
        """Suppress default access log — we log events ourselves."""
        pass


def main():
    log.info("Gitea PR Reviewer webhook handler starting")

    # Setup Claude auth from env
    claude_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not claude_token:
        claude_token = core.read_secret("claude_code_oauth_token", required=False)
    if claude_token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token

    # Optional: Gemini and Codex
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(key, "")
        if not val:
            val = core.read_secret(key.lower(), required=False)
        if val:
            os.environ[key] = val

    config = core.load_config()

    auto_lenses = config.get("auto_lenses", ["simplification", "security"])
    WebhookHandler.config = config

    server = HTTPServer(("0.0.0.0", LISTEN_PORT), WebhookHandler)
    log.info("Listening on port %d", LISTEN_PORT)
    log.info("Gitea URL: %s, Org: %s", GITEA_URL, GITEA_ORG)
    log.info("Auto-review lenses: %s", auto_lenses)
    log.info("Webhook signature validation: %s", "enabled" if WEBHOOK_SECRET else "disabled")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        _executor.shutdown(wait=False)
        server.server_close()


if __name__ == "__main__":
    main()
