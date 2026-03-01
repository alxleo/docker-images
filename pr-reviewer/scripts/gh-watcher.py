#!/usr/bin/env python3
"""Poll GitHub for PR events and dispatch AI reviews.

Watches allowlisted private repos for:
- New non-draft PRs → auto-review at default depth
- Updated PRs (new commits) → re-review
- @review commands in PR comments → targeted review
- @claude questions → interactive follow-up (session resume)
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gh-watcher")

CONFIG_PATH = Path("/app/config.yml")
STATE_DIR = Path("/app/state")
REPOS_DIR = Path("/app/repos")
PROMPTS_DIR = Path("/app/prompts")

# Commands recognized in PR comments (no freeform prompts — injection risk)
COMMANDS = {
    "@review quick": "quick",
    "@review deep": "deep",
    "@review security": "security",
    "@review standards": "standards",
    "@review drift": "drift",
    "@review stop": "stop",
    "@review": "standard",  # must be last — prefix match
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def read_secret(path: str, required: bool = True) -> str:
    """Read a Docker secret from /run/secrets/ or env var fallback."""
    secret_file = os.environ.get(f"{path}_FILE", f"/run/secrets/{path}")
    if os.path.isfile(secret_file):
        val = Path(secret_file).read_text().strip()
        if val and not val.startswith("PLACEHOLDER"):
            return val
    # Fall back to env var (for local development)
    val = os.environ.get(path, "")
    if not val:
        if required:
            log.error("Secret %s not found at %s or in environment", path, secret_file)
            sys.exit(1)
        log.info("Optional secret %s not configured", path)
        return ""
    return val


def setup_auth():
    """Configure authentication from secrets."""
    claude_token = read_secret("claude_code_oauth_token")
    gh_token = read_secret("gh_token")
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
    os.environ["GH_TOKEN"] = gh_token

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
    log.info("Auth configured: %s + GitHub PAT", " + ".join(models))


def gh(args: str, repo: str | None = None) -> str:
    """Run a gh CLI command and return stdout."""
    cmd = ["gh"]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(args.split())
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error("gh %s failed: %s", args, result.stderr.strip())
        return ""
    return result.stdout


def gh_json(args: str, repo: str | None = None) -> list | dict:
    """Run a gh CLI command and parse JSON output."""
    output = gh(args, repo)
    if not output:
        return []
    return json.loads(output)


def load_state(repo: str, pr_number: int) -> dict:
    """Load review state for a PR."""
    safe_repo = repo.replace("/", "_")
    state_file = STATE_DIR / f"{safe_repo}_pr{pr_number}.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def save_state(repo: str, pr_number: int, state: dict):
    """Save review state for a PR."""
    safe_repo = repo.replace("/", "_")
    state_file = STATE_DIR / f"{safe_repo}_pr{pr_number}.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


def save_poll_timestamp():
    """Write last poll time for healthcheck."""
    ts_file = STATE_DIR / "last_poll.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts_file.write_text(json.dumps({"last_poll": time.time()}))


def clone_or_update(repo: str) -> Path:
    """Clone repo or pull latest. Returns repo directory."""
    safe_name = repo.replace("/", "_")
    repo_dir = REPOS_DIR / safe_name
    if repo_dir.exists():
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=repo_dir,
            capture_output=True,
            timeout=120,
        )
    else:
        REPOS_DIR.mkdir(parents=True, exist_ok=True)
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
    return gh(f"pr diff {pr_number}", repo=repo)


def enabled_lenses(config: dict, depth: str) -> list[dict]:
    """Return list of lenses to run for the given depth."""
    if depth in ("security", "standards", "drift", "simplification"):
        # Single-lens mode
        lens_name = depth
        lens_cfg = config["lenses"].get(lens_name, {})
        return [{"name": lens_name, "max_comments": lens_cfg.get("max_comments", 5)}]

    if depth == "quick":
        overrides = config.get("quick_overrides", {})
        lens_names = overrides.get("lenses", ["simplification"])
        max_comments = overrides.get("max_comments", 3)
        return [{"name": n, "max_comments": max_comments} for n in lens_names]

    # standard or deep
    lenses = []
    for name, cfg in config["lenses"].items():
        if not cfg.get("enabled", True):
            continue
        max_comments = cfg.get("max_comments", 5)
        if depth == "deep":
            max_comments = config.get("deep_overrides", {}).get("max_comments", 0)
        lenses.append({"name": name, "max_comments": max_comments})
    return lenses


def build_review_prompt(lens_name: str, diff: str, max_comments: int) -> str:
    """Build the full review prompt from lens template + diff."""
    prompt_file = PROMPTS_DIR / f"{lens_name}.md"
    if not prompt_file.exists():
        return ""

    system_instructions = prompt_file.read_text()
    constraint = ""
    if max_comments > 0:
        constraint = f"\n\nMAX COMMENTS: {max_comments}. If nothing is worth flagging, output nothing."

    return f"{system_instructions}\n\n---\n\nReview this PR diff:{constraint}\n\n```diff\n{diff}\n```"


def run_lens_claude(prompt: str, repo_dir: Path, max_turns: int) -> str:
    """Run review via Claude Code CLI."""
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--allowedTools", "Read,Glob,Grep",
        "--max-turns", str(max_turns),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    if result.returncode != 0:
        return ""
    try:
        output = json.loads(result.stdout)
        return output.get("result", "")
    except json.JSONDecodeError:
        return result.stdout.strip()


def run_lens_gemini(prompt: str, repo_dir: Path) -> str:
    """Run review via Gemini CLI."""
    if not os.environ.get("GEMINI_API_KEY"):
        return ""
    cmd = ["gemini", "-p", prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def run_lens_codex(prompt: str, repo_dir: Path) -> str:
    """Run review via Codex CLI."""
    if not os.environ.get("OPENAI_API_KEY"):
        return ""
    cmd = ["codex", "exec", prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


# Which model runs which lens (configurable via config.yml)
DEFAULT_MODEL = "claude"


def run_lens(lens: dict, diff: str, repo_dir: Path, config: dict) -> str:
    """Run a single review lens via the configured model."""
    lens_name = lens["name"]
    max_comments = lens["max_comments"]

    prompt = build_review_prompt(lens_name, diff, max_comments)
    if not prompt:
        log.warning("Prompt file missing for lens: %s", lens_name)
        return ""

    max_turns = 15 if max_comments == 0 else 5

    # Check lens-level model override, then global default
    model = config["lenses"].get(lens_name, {}).get("model", config.get("default_model", DEFAULT_MODEL))
    log.info("Running lens: %s via %s (max_comments=%s)", lens_name, model, max_comments)

    try:
        if model == "gemini":
            return run_lens_gemini(prompt, repo_dir)
        elif model == "codex":
            return run_lens_codex(prompt, repo_dir)
        else:
            return run_lens_claude(prompt, repo_dir, max_turns)
    except subprocess.TimeoutExpired:
        log.error("Lens %s (%s) timed out after 300s", lens_name, model)
        return ""


LENS_ICONS = {
    "simplification": "\U0001f50d",  # 🔍
    "standards": "\U0001f4cf",       # 📏
    "drift": "\U0001f504",           # 🔄
    "security": "\U0001f512",        # 🔒
}


def post_review(repo: str, pr_number: int, lens_name: str, body: str):
    """Post a review comment on the PR."""
    icon = LENS_ICONS.get(lens_name, "\U0001f50d")
    header = f"## {icon} {lens_name.title()} Review\n\n"
    full_body = header + body

    # gh pr comment via stdin to avoid shell escaping issues
    cmd = ["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body-file", "-"]
    result = subprocess.run(cmd, input=full_body, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        log.error("Failed to post review for PR #%d lens %s: %s", pr_number, lens_name, result.stderr)
    else:
        log.info("Posted %s review on %s#%d", lens_name, repo, pr_number)


def dispatch_review(config: dict, repo: str, pr_number: int, depth: str):
    """Run all enabled lenses against a PR and post results."""
    log.info("Reviewing %s#%d at depth=%s", repo, pr_number, depth)

    repo_dir = clone_or_update(repo)
    checkout_pr(repo_dir, pr_number)
    diff = get_diff(repo, pr_number)

    if not diff:
        log.warning("Empty diff for %s#%d, skipping", repo, pr_number)
        return

    lenses = enabled_lenses(config, depth)
    session_ids = {}

    for lens in lenses:
        result = run_lens(lens, diff, repo_dir, config)
        if result and result.strip():
            post_review(repo, pr_number, lens["name"], result)
        else:
            log.info("Lens %s: no issues found for %s#%d", lens["name"], repo, pr_number)

    # Update state
    state = load_state(repo, pr_number)
    state["last_reviewed_at"] = time.time()
    state["last_head_sha"] = get_head_sha(repo, pr_number)
    state["session_ids"] = session_ids
    save_state(repo, pr_number, state)


def get_head_sha(repo: str, pr_number: int) -> str:
    """Get the current head SHA of a PR."""
    pr_data = gh_json(f"pr view {pr_number} --json headRefOid", repo=repo)
    if isinstance(pr_data, dict):
        return pr_data.get("headRefOid", "")
    return ""


def needs_review(repo: str, pr: dict, state: dict) -> bool:
    """Check if a PR needs (re-)review based on state."""
    if not state:
        return True  # Never reviewed

    last_sha = state.get("last_head_sha", "")
    current_sha = pr.get("headRefOid", "")
    if current_sha and current_sha != last_sha:
        return True  # New commits since last review

    return False


def parse_command(comment_body: str) -> str | None:
    """Parse a review command from a comment body. Returns depth or None."""
    body = comment_body.strip().lower()
    for prefix, depth in COMMANDS.items():
        if body.startswith(prefix):
            return depth
    return None


def check_comments(config: dict, repo: str, pr_number: int, comments: list):
    """Check PR comments for @review commands."""
    state = load_state(repo, pr_number)
    processed_ids = set(state.get("processed_comment_ids", []))

    for comment in comments:
        comment_id = str(comment.get("id", ""))
        if comment_id in processed_ids:
            continue

        body = comment.get("body", "")
        depth = parse_command(body)
        if depth is None:
            continue

        processed_ids.add(comment_id)

        if depth == "stop":
            log.info("Stop command received for %s#%d", repo, pr_number)
            # Just mark as processed, don't review
        else:
            dispatch_review(config, repo, pr_number, depth)

    state["processed_comment_ids"] = list(processed_ids)
    save_state(repo, pr_number, state)


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
                "pr list --state open --json number,updatedAt,isDraft,headRefOid,comments",
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

            state = load_state(repo, pr_number)

            # Check for @review commands in comments
            comments = pr.get("comments", [])
            if comments:
                check_comments(config, repo, pr_number, comments)

            # Auto-review if new or updated
            if needs_review(repo, pr, state):
                depth = config.get("default_depth", "standard")
                dispatch_review(config, repo, pr_number, depth)

    save_poll_timestamp()


def main():
    log.info("PR Reviewer starting")

    config = load_config()
    setup_auth()

    log.info(
        "Watching %d repos, polling every %ds, default depth: %s",
        len(config.get("repos", [])),
        config.get("polling_interval", 60),
        config.get("default_depth", "standard"),
    )

    interval = config.get("polling_interval", 60)

    while True:
        try:
            poll(config)
        except Exception:
            log.exception("Poll cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
