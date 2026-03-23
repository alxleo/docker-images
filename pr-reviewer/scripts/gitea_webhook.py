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


def post_review(client: httpx.Client, owner: str, repo: str, pr_number: int,
                lens_name: str, body: str, head_sha: str, diff: str = ""):
    """Post review on a Gitea PR — inline comments if possible, fallback to top-level."""
    icon = core.LENS_ICONS.get(lens_name, "\U0001f50d")

    # Try inline review via Gitea's review API
    if diff:
        comments = core.parse_inline_comments(body, diff)
        if comments and head_sha:
            review_body = f"{icon} **{lens_name.title()} Review** — {len(comments)} finding(s)"
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
    full_body = header + body
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
        diff = get_diff(client, owner, repo, pr_number)
        if not diff:
            log.warning("Empty diff for %s/%s#%d, skipping", owner, repo, pr_number)
            return

        # Fetch PR metadata for richer context
        pr_description = ""
        commit_messages = ""
        r = client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        if r.status_code == 200:
            pr_data = r.json()
            pr_description = pr_data.get("body", "") or ""
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

        lenses = core.enabled_lenses(config, depth)

        for lens in lenses:
            result = core.run_lens(lens, diff, repo_dir, config,
                                   commit_messages=commit_messages,
                                   pr_description=pr_description,
                                   model_override=model_override)
            if result and result.strip():
                post_review(client, owner, repo, pr_number,
                            lens["name"], result, head_sha, diff=diff)
            else:
                log.info("Lens %s: no issues found for %s/%s#%d",
                         lens["name"], owner, repo, pr_number)

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
