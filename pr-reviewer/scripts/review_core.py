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
                        commit_messages: str = "", pr_description: str = "",
                        repomap: str = "", impact: str = "") -> str:
    """Build the full review prompt from preamble + lens template + context + diff."""
    prompt_file = PROMPTS_DIR / f"{lens_name}.md"
    if not prompt_file.exists():
        return ""

    # Load shared preamble (anti-hallucination rules, tool instructions, output format)
    preamble_file = PROMPTS_DIR / "_preamble.md"
    preamble = preamble_file.read_text() if preamble_file.exists() else ""

    lens_instructions = prompt_file.read_text()
    constraint = ""
    if max_comments > 0:
        constraint = f"\n\nMAX COMMENTS: {max_comments}. If nothing is worth flagging, output nothing."

    context = ""
    if pr_description:
        context += f"\n\n## PR Description\n\n{pr_description}"
    if commit_messages:
        context += f"\n\n## Commit Messages\n\n{commit_messages}"
    if repomap:
        context += f"\n\n## Repository Structure\n\n{repomap}"
    if impact:
        context += f"\n\n## Impact Analysis\n\n{impact}"

    # Preprocess diff: strip delete-only hunks, add language annotations, token budget
    processed_diff = preprocess_diff(diff)

    return (f"{preamble}\n\n{lens_instructions}\n\n---\n\n"
            f"Review this PR diff:{constraint}{context}\n\n```diff\n{processed_diff}\n```")


# ---------------------------------------------------------------------------
# Repomap — structural overview of the codebase via tree-sitter
# ---------------------------------------------------------------------------

# Top-level AST node types that represent definitions, by language
_DEFINITION_TYPES = {
    "function_definition", "class_definition", "decorated_definition",  # Python
    "function_declaration", "class_declaration", "method_definition",   # JS/TS/Go
    "interface_declaration", "type_alias_declaration", "enum_declaration",  # TS
    "struct_item", "impl_item", "fn_item", "enum_item", "trait_item",  # Rust
    "function_definition",  # C/C++
}


def generate_repomap(repo_dir: Path, max_chars: int = 8000) -> str:
    """Generate a compact structural map of the repo using tree-sitter.

    Returns a text overview of top-level definitions per file, truncated to
    max_chars. Useful as context for LLM code review — like a table of contents.
    """
    try:
        from grep_ast import filename_to_lang
        from tree_sitter_language_pack import get_language
        from tree_sitter import Parser
    except ImportError:
        log.info("grep-ast not installed — skipping repomap")
        return ""

    lines = []
    total = 0
    files_processed = 0
    max_files = 200  # Safety cap — don't spend forever indexing huge repos

    # Walk source files, skip hidden dirs and common non-code
    skip_dirs = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv",
                 "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", "egg-info"}
    source_files = []
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") or part in skip_dirs for part in path.relative_to(repo_dir).parts):
            continue
        source_files.append(path)
        if len(source_files) >= max_files:
            break
    source_files.sort()

    for path in source_files:
        rel = str(path.relative_to(repo_dir))

        lang_name = filename_to_lang(rel)
        if not lang_name:
            continue
        # Skip languages with broken/slow grammars in tree-sitter-language-pack
        # and non-code files (markdown, yaml, toml) that don't have useful definitions
        if lang_name in ("bash", "markdown", "toml", "yaml", "json", "dockerfile",
                         "css", "html", "xml", "sql"):
            continue

        try:
            lang = get_language(lang_name)
            parser = Parser(lang)
            code = path.read_bytes()
            tree = parser.parse(code)
        except Exception:
            continue

        defs = []
        for node in tree.root_node.children:
            if node.type in _DEFINITION_TYPES:
                first_line = code[node.start_byte:node.end_byte].decode(errors="replace").split("\n")[0]
                defs.append(f"  {first_line.strip()}")

        if defs:
            file_block = f"{rel}:\n" + "\n".join(defs) + "\n"
            if total + len(file_block) > max_chars:
                lines.append("... (truncated)\n")
                break
            lines.append(file_block)
            total += len(file_block)

    return "".join(lines)


PLUGINS_DIR = Path("/app/plugins")
PLUGIN_DIR = Path("/app/plugin")  # built-in reviewer plugin with lens agents

# Tool whitelist for Claude during review — READ-ONLY
# Bash restricted to read-only git commands and ast-grep. No Edit, Write, or git push/commit.
CLAUDE_REVIEW_TOOLS = ",".join([
    "Read", "Glob", "Grep",
    "Bash(git log:*)", "Bash(git blame:*)", "Bash(git diff:*)", "Bash(git show:*)",
    "Bash(sg:*)",
    "WebSearch", "WebFetch",
    "Agent",
])

# Default model config — overridden by config.yml
DEFAULT_MODELS = {
    "claude": "sonnet",
    "claude_deep": "opus",
    "gemini": "gemini-2.5-pro",
    "codex": "o3",
}


def _resolve_model(config: dict, model_family: str, depth: str = "standard") -> str:
    """Resolve the actual model name from config.

    For Claude, uses claude_deep model when depth is 'deep'.
    """
    models = config.get("models", DEFAULT_MODELS)
    if model_family == "claude" and depth == "deep":
        return models.get("claude_deep", models.get("claude", "sonnet"))
    return models.get(model_family, DEFAULT_MODELS.get(model_family, model_family))


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


def run_lens_claude(prompt: str, repo_dir: Path, max_turns: int,
                    model: str = "sonnet") -> str:
    """Run review via Claude Code CLI. Fully deterministic invocation."""
    cmd = [
        "claude",
        "-p",
        "--model", model,
        "--output-format", "json",
        "--allowedTools", CLAUDE_REVIEW_TOOLS,
        "--max-turns", str(max_turns),
    ]
    # Load built-in reviewer plugin (lens agent definitions)
    if PLUGIN_DIR.is_dir() and (PLUGIN_DIR / ".claude-plugin").is_dir():
        cmd.extend(["--plugin-dir", str(PLUGIN_DIR)])
    # Load marketplace plugins from the plugins volume
    if PLUGINS_DIR.is_dir():
        for plugin_dir in PLUGINS_DIR.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / ".claude-plugin").is_dir():
                cmd.extend(["--plugin-dir", str(plugin_dir)])
    start = time.time()
    log.info("Claude invocation: --model %s --max-turns %d", model, max_turns)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("claude", result, time.time() - start)
    if result.returncode != 0:
        return ""
    try:
        output = json.loads(result.stdout)
        return output.get("result", "")
    except json.JSONDecodeError:
        return result.stdout.strip()


def run_lens_gemini(prompt: str, repo_dir: Path, model: str = "gemini-2.5-pro") -> str:
    """Run review via Gemini CLI. Fully deterministic invocation.

    Gemini requires -p as a string arg (not stdin). Short instruction via -p,
    full prompt via stdin.
    """
    cmd = ["gemini", "-p", "Review the code below. Follow the system instructions provided via stdin exactly.",
           "-m", model]
    start = time.time()
    log.info("Gemini invocation: -m %s", model)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("gemini", result, time.time() - start)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def run_lens_codex(prompt: str, repo_dir: Path, model: str = "o3") -> str:
    """Run review via Codex CLI. Fully deterministic invocation.

    Uses `codex exec` (not `codex exec review` — websocket API broken with OAuth).
    """
    cmd = ["codex", "exec", "-m", model]
    start = time.time()
    log.info("Codex invocation: -m %s", model)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("codex", result, time.time() - start)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Diff relevance routing
# ---------------------------------------------------------------------------

# Patterns that indicate a lens is relevant for the diff content
_SECURITY_PATTERNS = {"secret", "password", "token", "key", "auth", "env_file",
                      "0.0.0.0", "privileged", "cap_drop", "cap_add", "permission"}
_CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt"}
_CONFIG_EXTENSIONS = {".yml", ".yaml", ".toml", ".json", ".env", ".cfg", ".ini"}
_INFRA_EXTENSIONS = {".tf", ".hcl", ".dockerfile"}


def analyze_diff_relevance(diff: str) -> set[str]:
    """Determine which lenses are relevant based on diff content. Zero LLM cost."""
    relevant = set()
    diff_lower = diff.lower()

    # Extract changed file extensions
    changed_exts = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            filename = line[6:]
            ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
            changed_exts.add(ext.lower())
            if filename.lower().startswith("dockerfile"):
                changed_exts.add(".dockerfile")

    # Route by content and file type
    has_code = bool(changed_exts & _CODE_EXTENSIONS)
    has_config = bool(changed_exts & _CONFIG_EXTENSIONS)
    has_infra = bool(changed_exts & _INFRA_EXTENSIONS)
    has_new_files = "new file mode" in diff_lower

    if has_code:
        relevant.add("simplification")
    if any(pattern in diff_lower for pattern in _SECURITY_PATTERNS) or has_infra:
        relevant.add("security")
    if has_config or has_infra:
        relevant.add("standards")
    if has_new_files or has_config:
        relevant.add("drift")
    if has_new_files or has_infra:
        relevant.add("architecture")

    # Default: at least simplification + security
    return relevant or {"simplification", "security"}


def run_lens(lens: dict, diff: str, repo_dir: Path, config: dict,
             commit_messages: str = "", pr_description: str = "",
             model_override: str | None = None, repomap: str = "",
             depth: str = "standard", impact: str = "") -> str:
    """Run a single review lens via the configured model. Fully deterministic."""
    lens_name = lens["name"]
    max_comments = lens["max_comments"]

    prompt = build_review_prompt(lens_name, diff, max_comments,
                                commit_messages=commit_messages,
                                pr_description=pr_description,
                                repomap=repomap,
                                impact=impact)
    if not prompt:
        log.warning("Prompt file missing for lens: %s", lens_name)
        return ""

    max_turns = 15 if max_comments == 0 else 5

    # Model priority: command override > lens config > global default
    model_family = (model_override
                    or config.get("lenses", {}).get(lens_name, {}).get("model")
                    or config.get("default_model", DEFAULT_MODEL))
    model_name = _resolve_model(config, model_family, depth)
    log.info("Running lens: %s via %s (model=%s, max_comments=%s)",
             lens_name, model_family, model_name, max_comments)

    try:
        if model_family == "gemini":
            return run_lens_gemini(prompt, repo_dir, model=model_name)
        elif model_family == "codex":
            return run_lens_codex(prompt, repo_dir, model=model_name)
        else:
            return run_lens_claude(prompt, repo_dir, max_turns, model=model_name)
    except subprocess.TimeoutExpired:
        log.error("Lens %s (%s) timed out after 300s", lens_name, model_family)
        return ""


# ---------------------------------------------------------------------------
# Orchestrated review — single Claude session spawns lens sub-agents
# ---------------------------------------------------------------------------


def run_review_orchestrated(lenses: list[dict], diff: str, repo_dir: Path, config: dict,
                            commit_messages: str = "", pr_description: str = "",
                            model_override: str | None = None, repomap: str = "",
                            depth: str = "standard", impact: str = "") -> list[tuple[str, str]]:
    """Run multiple lenses in a single Claude session via sub-agents.

    Instead of N × claude -p (one per lens), this runs one orchestrator session
    that spawns each lens as a sub-agent via the Agent tool. Saves rate limit
    budget and allows lenses to share context.

    For non-Claude models, falls back to individual run_lens() calls.

    Returns list of (lens_name, result) tuples for findings.
    """
    # Split lenses by model family — anything not explicitly gemini/codex goes to Claude
    claude_lenses = []
    other_lenses = []
    for lens in lenses:
        lens_model = (model_override
                      or config.get("lenses", {}).get(lens["name"], {}).get("model")
                      or config.get("default_model", DEFAULT_MODEL))
        if lens_model in ("gemini", "codex"):
            other_lenses.append(lens)
        else:
            claude_lenses.append(lens)

    results = []

    # Run Claude lenses via single orchestrated session
    if claude_lenses:
        model_name = _resolve_model(config, "claude", depth)
        max_turns = 20 if depth == "deep" else 10
        lens_names = [l["name"] for l in claude_lenses]

        # Build orchestrator prompt
        preamble_file = PROMPTS_DIR / "_preamble.md"
        preamble = preamble_file.read_text() if preamble_file.exists() else ""

        context = ""
        if pr_description:
            context += f"\n\n## PR Description\n\n{pr_description}"
        if commit_messages:
            context += f"\n\n## Commit Messages\n\n{commit_messages}"
        if repomap:
            context += f"\n\n## Repository Structure\n\n{repomap}"
        if impact:
            context += f"\n\n## Impact Analysis\n\n{impact}"

        processed_diff = preprocess_diff(diff)
        # Shuffle file order to break positional bias (LLMs fixate on early files)
        if config.get("shuffle_diff", True):
            processed_diff = shuffle_diff(processed_diff)

        orchestrator_prompt = f"""{preamble}

You are a PR review orchestrator. Your job is to spawn specialized review agents and collect their findings.

For each of the following lenses, spawn the corresponding agent using the Agent tool:
{chr(10).join(f'- **{name}** → spawn agent `pr-reviewer-lenses:{name}-lens`' for name in lens_names)}

Pass each agent the PR diff below as its task. Collect all findings.

After all agents complete, output ALL findings combined. Use the exact output format from each agent — do not summarize or rewrite their findings. If an agent found nothing, skip it silently.
{context}

## PR Diff

```diff
{processed_diff}
```"""

        log.info("Orchestrated review: %d Claude lenses via single session (model=%s, max_turns=%d)",
                 len(claude_lenses), model_name, max_turns)

        result = run_lens_claude(orchestrator_prompt, repo_dir, max_turns, model=model_name)
        if result and result.strip():
            # Post as the first lens name for cleanup tagging. The orchestrator
            # aggregates all lens findings into one output.
            label = lens_names[0] if len(lens_names) == 1 else "review"
            results.append((label, result))

    # Run non-Claude lenses individually (Gemini, Codex)
    for lens in other_lenses:
        result = run_lens(lens, diff, repo_dir, config,
                          commit_messages=commit_messages,
                          pr_description=pr_description,
                          model_override=model_override,
                          repomap=repomap, depth=depth, impact=impact)
        if result and result.strip():
            results.append((lens["name"], result))

    return results


# ---------------------------------------------------------------------------
# Diff preprocessing
# ---------------------------------------------------------------------------


def shuffle_diff(raw_diff: str) -> str:
    """Shuffle file order in a unified diff to break positional bias.

    LLMs fixate on early files and miss issues in later ones. Randomizing
    file order each review produces different attention patterns.

    Handles both raw diffs (split on `diff --git`) and preprocessed diffs
    (split on `## filename` headers from preprocess_diff).
    """
    import random

    # Detect format: preprocessed diffs start sections with "## "
    if "\n## " in raw_diff or raw_diff.startswith("## "):
        # Preprocessed format — split on ## headers
        import re
        sections = re.split(r'(?=^## )', raw_diff, flags=re.MULTILINE)
        sections = [s for s in sections if s.strip()]
        if len(sections) <= 1:
            return raw_diff
        random.shuffle(sections)
        return "\n".join(sections)

    # Raw unified diff format — split on diff --git
    files: list[tuple[str, str]] = []
    current_lines: list[str] = []
    current_file = ""

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_file and current_lines:
                files.append((current_file, "".join(current_lines)))
            current_lines = [line]
            parts = line.strip().split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else ""
        else:
            current_lines.append(line)

    if current_file and current_lines:
        files.append((current_file, "".join(current_lines)))

    if len(files) <= 1:
        return raw_diff

    random.shuffle(files)
    return "".join(content for _, content in files)


# Language detection by file extension
_EXT_TO_LANG = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java", ".kt": "Kotlin",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".json": "JSON",
    ".md": "Markdown", ".tf": "Terraform", ".hcl": "HCL",
    ".dockerfile": "Dockerfile", ".sql": "SQL", ".css": "CSS", ".html": "HTML",
}


def preprocess_diff(raw_diff: str, max_tokens: int = 30000) -> str:
    """Preprocess a unified diff for better LLM consumption.

    1. Strip delete-only files (files with no additions — reviews focus on new code)
    2. Annotate files with language
    3. If over token budget, sort files by size and truncate

    Returns processed diff string.
    """
    if not raw_diff.strip():
        return raw_diff

    # Split diff into per-file chunks
    files: list[tuple[str, str]] = []  # (filename, diff_text)
    current_file = ""
    current_lines: list[str] = []

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_file and current_lines:
                files.append((current_file, "".join(current_lines)))
            current_lines = [line]
            # Extract filename from "diff --git a/path b/path"
            parts = line.strip().split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else ""
        else:
            current_lines.append(line)

    if current_file and current_lines:
        files.append((current_file, "".join(current_lines)))

    if not files:
        return raw_diff

    # Process each file: strip delete-only hunks, add language annotation
    processed = []
    for filename, diff_text in files:
        # Check if this file's diff is delete-only (no added lines)
        has_additions = any(
            line.startswith("+") and not line.startswith("+++")
            for line in diff_text.splitlines()
        )
        if not has_additions:
            continue  # Skip delete-only files

        # Add language annotation header
        ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        lang = _EXT_TO_LANG.get(ext.lower(), "")
        if filename.lower().startswith("dockerfile"):
            lang = "Dockerfile"
        header = f"## {filename}" + (f" [{lang}]" if lang else "") + "\n"

        processed.append((filename, header + diff_text))

    # Token budget check (rough: 1 token ≈ 4 chars)
    total_chars = sum(len(d) for _, d in processed)
    token_estimate = total_chars // 4

    if token_estimate > max_tokens:
        # Sort: smallest files first (most likely to be meaningful changes)
        processed.sort(key=lambda x: len(x[1]))
        kept = []
        budget = max_tokens * 4
        used = 0
        skipped = []
        for filename, diff_text in processed:
            if used + len(diff_text) > budget:
                skipped.append(filename)
            else:
                kept.append(diff_text)
                used += len(diff_text)
        result = "\n".join(kept)
        if skipped:
            result += f"\n\n(Skipped {len(skipped)} large files due to token budget: {', '.join(skipped)})\n"
        return result

    return "\n".join(d for _, d in processed)


# ---------------------------------------------------------------------------
# Impact analysis — find references to changed files (zero LLM cost)
# ---------------------------------------------------------------------------


def analyze_impact(repo_dir: Path, diff: str, max_refs: int = 20) -> str:
    """Find files that reference each changed file. Cheap grep-based pre-pass.

    Returns a text summary like:
        scripts/foo.py: referenced by tests/test_foo.py, scripts/bar.py
    """
    # Extract changed filenames from diff
    changed_files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            changed_files.append(line[6:])

    if not changed_files:
        return ""

    impacts = []
    for filepath in changed_files:
        # Get the module/file name to search for
        basename = Path(filepath).stem
        if not basename or basename.startswith("."):
            continue

        # Search for references (imports, includes, requires)
        try:
            result = subprocess.run(
                ["rg", "-l", "--max-count=1", basename,
                 "--glob", f"!{filepath}",  # exclude the file itself
                 "--glob", "!*.lock", "--glob", "!*.min.*"],
                capture_output=True, text=True, cwd=repo_dir, timeout=10,
            )
            refs = [r for r in result.stdout.strip().splitlines() if r][:max_refs]
            if refs:
                impacts.append(f"{filepath}: referenced by {', '.join(refs)}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    if not impacts:
        return ""

    return "Files affected by this change:\n" + "\n".join(impacts)


# ---------------------------------------------------------------------------
# Severity parsing + capping
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def cap_by_severity(body: str, max_comments: int) -> str:
    """If the review has more findings than max_comments, keep the highest severity.

    Parses ### [SEVERITY] markers, sorts by severity, drops the lowest.
    Returns the body with only the kept findings.
    """
    if max_comments <= 0:
        return body  # unlimited

    # Split into findings by ### markers
    finding_pattern = re.compile(r'^(###\s+\[(?:CRITICAL|HIGH|MEDIUM|LOW)\].*?)(?=\n###\s+\[|\Z)',
                                 re.MULTILINE | re.DOTALL)
    findings = finding_pattern.findall(body)

    if len(findings) <= max_comments:
        return body  # under the cap

    # Extract severity from each finding
    scored = []
    for finding in findings:
        sev_match = re.match(r'###\s+\[(CRITICAL|HIGH|MEDIUM|LOW)\]', finding)
        sev = _SEVERITY_ORDER.get(sev_match.group(1), 99) if sev_match else 99
        scored.append((sev, finding))

    # Sort by severity (lowest number = highest priority), keep top N
    scored.sort(key=lambda x: x[0])
    kept = scored[:max_comments]
    dropped = len(scored) - max_comments

    # Reconstruct body: preamble (text before first finding) + kept findings
    first_finding_pos = body.find(findings[0]) if findings else len(body)
    preamble = body[:first_finding_pos]
    result = preamble + "\n\n".join(f for _, f in kept)
    if dropped > 0:
        result += f"\n\n*(Dropped {dropped} lower-severity finding(s) due to comment cap)*"

    return result


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
