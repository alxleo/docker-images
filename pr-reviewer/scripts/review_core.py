"""Shared review engine — forge-agnostic lens dispatch, comment parsing, state management.

Used by both gh_watcher.py (GitHub poller) and gitea_webhook.py (Gitea webhook handler).
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths (monkeypatched in tests)
# ---------------------------------------------------------------------------

CONFIG_PATH = Path("/app/config.yml")
STATE_DIR = Path("/app/state")
REPOS_DIR = Path("/app/repos")
PROMPTS_DIR = Path("/app/prompts")

# ---------------------------------------------------------------------------
# Commands & icons
# ---------------------------------------------------------------------------

# Commands recognized in PR comments (no freeform prompts — injection risk)
# Supports optional "with <model>" suffix: "@pr-reviewer security with gemini"
COMMANDS = {
    "@pr-reviewer quick": "quick",
    "@pr-reviewer deep": "deep",
    "@pr-reviewer security": "security",
    "@pr-reviewer standards": "standards",
    "@pr-reviewer drift": "drift",
    "@pr-reviewer simplification": "simplification",
    "@pr-reviewer architecture": "architecture",
    "@pr-reviewer stop": "stop",
    "@pr-reviewer": "standard",  # must be last — prefix match
}

VALID_MODELS = {"claude", "gemini", "codex"}

LENS_ICONS = {
    "simplification": "\U0001f50d",  # 🔍
    "standards": "\U0001f4cf",       # 📏
    "drift": "\U0001f504",           # 🔄
    "security": "\U0001f512",        # 🔒
    "architecture": "\U0001f3db",    # 🏛
}

DEFAULT_MODEL = "claude"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Lens system
# ---------------------------------------------------------------------------


def enabled_lenses(config: dict, depth: str) -> list[dict]:
    """Return list of lenses to run for the given depth."""
    if depth in ("security", "standards", "drift", "simplification", "architecture"):
        # Single-lens mode
        lens_name = depth
        lens_cfg = config["lenses"].get(lens_name, {})
        return [{"name": lens_name, "max_comments": lens_cfg.get("max_comments", 5)}]

    if depth == "quick":
        overrides = config.get("quick_overrides", {})
        lens_names = overrides.get("lenses", ["simplification"])
        max_comments = overrides.get("max_comments", 3)
        return [{"name": n, "max_comments": max_comments} for n in lens_names]

    if depth == "auto":
        auto_lenses = config.get("auto_lenses", ["simplification", "security"])
        max_comments = config.get("auto_overrides", {}).get("max_comments", 5)
        return [{"name": n, "max_comments": max_comments} for n in auto_lenses]

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


def build_review_prompt(lens_name: str, diff: str, max_comments: int,
                        commit_messages: str = "", pr_description: str = "") -> str:
    """Build the full review prompt from lens template + diff + context."""
    prompt_file = PROMPTS_DIR / f"{lens_name}.md"
    if not prompt_file.exists():
        return ""

    system_instructions = prompt_file.read_text()
    constraint = ""
    if max_comments > 0:
        constraint = f"\n\nMAX COMMENTS: {max_comments}. If nothing is worth flagging, output nothing."

    context = ""
    if pr_description:
        context += f"\n\n## PR Description\n\n{pr_description}"
    if commit_messages:
        context += f"\n\n## Commit Messages\n\n{commit_messages}"

    tools_note = ("\n\nYou have access to git history (git log, git blame) and web search. "
                  "Use them to understand WHY code looks the way it does before flagging it. "
                  "Check project CLAUDE.md for conventions if it exists.")

    return (f"{system_instructions}{tools_note}\n\n---\n\n"
            f"Review this PR diff:{constraint}{context}\n\n```diff\n{diff}\n```")


PLUGINS_DIR = Path("/app/plugins")

# Tools available to Claude during review:
# - Read/Glob/Grep: code navigation (uses ripgrep + fd when available)
# - Bash(git *): git log, blame, history for context on why code looks the way it does
# - WebSearch/WebFetch: check docs, research patterns, verify API usage
REVIEW_TOOLS = "Read,Glob,Grep,Bash(git:*),WebSearch,WebFetch"


def _log_lens_result(model: str, result: subprocess.CompletedProcess, duration_s: float):
    """Log lens execution result for observability."""
    status = "ok" if result.returncode == 0 else f"exit={result.returncode}"
    stdout_len = len(result.stdout.strip())
    stderr_preview = result.stderr.strip()[:200] if result.stderr.strip() else ""
    log.info("Lens %s completed: %s, stdout=%d chars, %.1fs%s",
             model, status, stdout_len, duration_s,
             f", stderr={stderr_preview}" if stderr_preview else "")
    if result.returncode != 0:
        log.warning("Lens %s failed (exit %d): %s", model, result.returncode,
                    result.stderr.strip()[:500] or result.stdout.strip()[:500])


def run_lens_claude(prompt: str, repo_dir: Path, max_turns: int) -> str:
    """Run review via Claude Code CLI."""
    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
        "--allowedTools", REVIEW_TOOLS,
        "--max-turns", str(max_turns),
    ]
    # Load plugins from the plugins volume if any are installed
    if PLUGINS_DIR.is_dir():
        for plugin_dir in PLUGINS_DIR.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / ".claude-plugin").is_dir():
                cmd.extend(["--plugin-dir", str(plugin_dir)])
    start = time.time()
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("claude", result, time.time() - start)
    if result.returncode != 0:
        return ""
    try:
        output = json.loads(result.stdout)
        return output.get("result", "")
    except json.JSONDecodeError:
        return result.stdout.strip()


def run_lens_gemini(prompt: str, repo_dir: Path) -> str:
    """Run review via Gemini CLI. Auth: GEMINI_API_KEY env var or mounted OAuth creds.

    Gemini requires -p as a string arg (not stdin). The prompt is passed via -p,
    with stdin used for additional context (diff). Since -p has length limits,
    we pass a short instruction via -p and the full prompt via stdin.
    """
    cmd = ["gemini", "-p", "Review the code below. Follow the system instructions provided via stdin exactly."]
    start = time.time()
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("gemini", result, time.time() - start)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def run_lens_codex(prompt: str, repo_dir: Path) -> str:
    """Run review via Codex CLI. Auth: mounted auth.json or API key.

    Uses `codex exec` (not `codex exec review` — the review subcommand uses
    a websocket API that doesn't work with mounted OAuth credentials).
    """
    cmd = ["codex", "exec"]
    start = time.time()
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("codex", result, time.time() - start)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def run_lens(lens: dict, diff: str, repo_dir: Path, config: dict,
             commit_messages: str = "", pr_description: str = "",
             model_override: str | None = None) -> str:
    """Run a single review lens via the configured model."""
    lens_name = lens["name"]
    max_comments = lens["max_comments"]

    prompt = build_review_prompt(lens_name, diff, max_comments,
                                commit_messages=commit_messages,
                                pr_description=pr_description)
    if not prompt:
        log.warning("Prompt file missing for lens: %s", lens_name)
        return ""

    max_turns = 15 if max_comments == 0 else 5

    # Model priority: command override > lens config > global default
    model = (model_override
             or config["lenses"].get(lens_name, {}).get("model")
             or config.get("default_model", DEFAULT_MODEL))
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


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------


def parse_inline_comments(body: str, diff: str) -> list[dict]:
    """Extract inline comments from review output using ### [file:line] pattern.

    Returns list of dicts with 'path', 'line', 'body' for each finding.
    Only returns comments where the file:line appears in the PR diff.
    """
    # Build set of (file, line) pairs that appear in the diff
    diff_lines: set[tuple[str, int]] = set()
    current_file = None
    current_line = 0
    for diff_line in diff.splitlines():
        if diff_line.startswith("+++ b/"):
            current_file = diff_line[6:]
        elif diff_line.startswith("@@ "):
            # Parse hunk header: @@ -old,count +new,count @@
            match = re.search(r'\+(\d+)', diff_line)
            if match:
                current_line = int(match.group(1))
        elif current_file:
            if diff_line.startswith("+") or diff_line.startswith(" "):
                diff_lines.add((current_file, current_line))
                current_line += 1
            elif diff_line.startswith("-"):
                pass  # deleted lines don't increment new-file line counter

    # Parse findings: ### [file:line] or ### [SEVERITY] [file:line]
    pattern = re.compile(r'^###\s+(?:\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]\s+)?\[([^:\]]+):(\d+)\]', re.MULTILINE)
    findings = list(pattern.finditer(body))

    if not findings:
        return []

    comments = []
    for i, match in enumerate(findings):
        file_path = match.group(1)
        line_num = int(match.group(2))

        # Extract body: everything from this heading to the next heading (or end)
        start = match.end()
        end = findings[i + 1].start() if i + 1 < len(findings) else len(body)
        comment_body = body[start:end].strip()

        # Only post inline if the line is in the diff
        if (file_path, line_num) in diff_lines:
            comments.append({"path": file_path, "line": line_num, "body": comment_body})
        else:
            # Try nearby lines (model might be off by a few)
            posted = False
            for offset in range(1, 4):
                for candidate in (line_num + offset, line_num - offset):
                    if (file_path, candidate) in diff_lines:
                        comments.append({"path": file_path, "line": candidate, "body": comment_body})
                        posted = True
                        break
                if posted:
                    break

    return comments


def parse_command(comment_body: str) -> tuple[str, str | None] | None:
    """Parse a review command from a comment body.

    Returns (depth, model_override) or None if not a command.
    model_override is None unless "with <model>" suffix is present.

    Examples:
        "@pr-reviewer"                → ("standard", None)
        "@pr-reviewer security"       → ("security", None)
        "@pr-reviewer with gemini"    → ("standard", "gemini")
        "@pr-reviewer deep with codex" → ("deep", "codex")
    """
    body = comment_body.strip().lower()
    for prefix, depth in COMMANDS.items():
        if body.startswith(prefix):
            remainder = body[len(prefix):].strip()
            model = None
            if remainder.startswith("with "):
                candidate = remainder[5:].strip().split()[0] if remainder[5:].strip() else ""
                if candidate in VALID_MODELS:
                    model = candidate
            return (depth, model)
    return None
