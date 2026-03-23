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

# Re-export core attributes so existing tests that do `w.STATE_DIR` etc. still work.
# Tests monkeypatch these, and the core functions read from core.STATE_DIR etc.,
# so we also need to patch the canonical location. The test fixture handles this
# by patching both `w.*` and `core.*` — but for backwards compat, expose them here.
CONFIG_PATH = core.CONFIG_PATH
STATE_DIR = core.STATE_DIR
REPOS_DIR = core.REPOS_DIR
PROMPTS_DIR = core.PROMPTS_DIR
COMMANDS = core.COMMANDS
LENS_ICONS = core.LENS_ICONS

# Re-export core functions used by tests and by this module's orchestration code
load_config = core.load_config
read_secret = core.read_secret
load_state = core.load_state
save_state = core.save_state
enabled_lenses = core.enabled_lenses
build_review_prompt = core.build_review_prompt
run_lens_claude = core.run_lens_claude
run_lens_gemini = core.run_lens_gemini
run_lens_codex = core.run_lens_codex
run_lens = core.run_lens
parse_inline_comments = core.parse_inline_comments
parse_command = core.parse_command


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
    claude_token = read_secret("claude_code_oauth_token")
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token

    # GitHub App auth — installation tokens rotate hourly
    app_id = read_secret("gh_app_id")
    installation_id = read_secret("gh_app_installation_id")
    private_key = read_secret("gh_app_private_key")
    app_auth = GitHubAppAuth(int(app_id), int(installation_id), private_key)

    # Set initial token so gh CLI works immediately
    os.environ["GH_TOKEN"] = app_auth.get_token()

    # Optional: Gemini and Codex for multi-model review
    gemini_key = read_secret("gemini_api_key", required=False)
    openai_key = read_secret("openai_api_key", required=False)
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def dispatch_review(config: dict, repo: str, pr_number: int, depth: str):
    """Run all enabled lenses against a PR and post results."""
    log.info("Reviewing %s#%d at depth=%s", repo, pr_number, depth)

    repo_dir = clone_or_update(repo)
    checkout_pr(repo_dir, pr_number)
    diff = get_diff(repo, pr_number)

    if not diff:
        log.warning("Empty diff for %s#%d, skipping", repo, pr_number)
        return

    lenses = core.enabled_lenses(config, depth)

    for lens in lenses:
        result = core.run_lens(lens, diff, repo_dir, config)
        if result and result.strip():
            post_review(repo, pr_number, lens["name"], result, diff=diff)
        else:
            log.info("Lens %s: no issues found for %s#%d", lens["name"], repo, pr_number)

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
        depth = core.parse_command(body)
        if depth is None:
            continue

        processed_ids.add(comment_id)

        if depth == "stop":
            log.info("Stop command received for %s#%d", repo, pr_number)
        else:
            dispatch_review(config, repo, pr_number, depth)

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

    config = load_config()
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
