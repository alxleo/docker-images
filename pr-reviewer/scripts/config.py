"""Configuration, constants, secrets, and state management."""

import json
import logging
import os
import sys
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
PLUGINS_DIR = Path("/app/plugins")
PLUGIN_DIR = Path("/app/plugin")  # built-in reviewer plugin with lens agents

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

# Default model config — overridden by config.yml
DEFAULT_MODELS = {
    "claude": "sonnet",
    "claude_deep": "opus",
    "gemini": "gemini-2.5-pro",
    "codex": "o3",
}

# Tool whitelist for Claude during review — READ-ONLY
# Bash restricted to read-only git commands and ast-grep. No Edit, Write, or git push/commit.
CLAUDE_REVIEW_TOOLS = ",".join([
    "Read", "Glob", "Grep",
    "Bash(git log:*)", "Bash(git blame:*)", "Bash(git diff:*)", "Bash(git show:*)",
    "Bash(sg:*)",
    "WebSearch", "WebFetch",
    "Agent",
])


# ---------------------------------------------------------------------------
# Config & secrets
# ---------------------------------------------------------------------------


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def read_secret(path: str, required: bool = True) -> str:
    """Read a Docker secret from /run/secrets/ or env var fallback."""
    secret_file = os.environ.get(f"{path}_FILE", f"/run/secrets/{path}")
    if os.path.isfile(secret_file):
        val = Path(secret_file).read_text().strip()
        if val and not val.startswith("PLACEHOLDER"):
            return val
    val = os.environ.get(path, "")
    if not val:
        if required:
            log.error("Secret %s not found at %s or in environment", path, secret_file)
            sys.exit(1)
        log.info("Optional secret %s not configured", path)
        return ""
    return val


def resolve_model(config: dict, model_family: str, depth: str = "standard") -> str:
    """Resolve the actual model name from config.

    For Claude, uses claude_deep model when depth is 'deep'.
    """
    models = config.get("models", DEFAULT_MODELS)
    if model_family == "claude" and depth == "deep":
        return models.get("claude_deep", models.get("claude", "sonnet"))
    return models.get(model_family, DEFAULT_MODELS.get(model_family, model_family))


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
# Lens selection
# ---------------------------------------------------------------------------


def enabled_lenses(config: dict, depth: str) -> list[dict]:
    """Return list of lenses to run for the given depth."""
    if depth in ("security", "standards", "drift", "simplification", "architecture"):
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


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


def parse_command(comment_body: str) -> tuple[str, str | None] | None:
    """Parse a review command from a comment body.

    Returns (depth, model_override) or None if not a command.
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
