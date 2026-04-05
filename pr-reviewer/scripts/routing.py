"""Lens routing: analyze diff relevance, dispatch to correct model."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from config import DEFAULT_MODEL, resolve_model
from models import run_lens_claude, run_lens_gemini, run_lens_codex
from prompts import build_review_prompt

log = logging.getLogger(__name__)

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

    changed_exts = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            filename = line[6:]
            ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
            changed_exts.add(ext.lower())
            if "dockerfile" in filename.lower():
                changed_exts.add(".dockerfile")

    has_code = bool(changed_exts & _CODE_EXTENSIONS)
    has_config = bool(changed_exts & _CONFIG_EXTENSIONS)
    has_infra = bool(changed_exts & _INFRA_EXTENSIONS)
    has_new_files = "new file mode" in diff_lower
    has_test_files = any(
        "test" in line[6:].lower()
        for line in diff.splitlines() if line.startswith("+++ b/")
    )
    has_public_api = (
        bool(changed_exts & {".proto", ".graphql", ".openapi"})
        or (has_code and "def " in diff)
    )

    if has_code:
        relevant.add("simplification")
    has_security_patterns = any(pattern in diff_lower for pattern in _SECURITY_PATTERNS)
    if any((has_security_patterns, has_infra)):
        relevant.add("security")
    if any((has_config, has_infra)):
        relevant.add("standards")
    if any((has_new_files, has_config)):
        relevant.add("drift")
    if any((has_new_files, has_infra)):
        relevant.add("architecture")
    if any((has_test_files, has_public_api)):
        relevant.add("meta")

    if not relevant:
        relevant = {"simplification", "security"}
    return relevant


def run_lens(lens: dict[str, Any], diff: str, repo_dir: Path, config: dict[str, Any],
             commit_messages: str = "", pr_description: str = "",
             model_override: str | None = None, repomap: str = "",
             depth: str = "standard", impact: str = "",
             cross_file_context: str = "") -> str:
    """Run a single review lens via the configured model. Fully deterministic."""
    lens_name = lens["name"]
    max_comments = lens["max_comments"]

    prompt = build_review_prompt(lens_name, diff, max_comments,
                                commit_messages=commit_messages,
                                pr_description=pr_description,
                                repomap=repomap, impact=impact,
                                cross_file_context=cross_file_context)
    if not prompt:
        log.warning("Prompt file missing for lens: %s", lens_name)
        return ""

    max_turns = 15 if max_comments == 0 else 5

    model_family = model_override
    if not model_family:
        model_family = config.get("lenses", {}).get(lens_name, {}).get("model", "")
    if not model_family:
        model_family = config.get("default_model", DEFAULT_MODEL)
    model_name = resolve_model(config, model_family, depth)
    log.info("Running lens: %s via %s (model=%s, max_comments=%s)",
             lens_name, model_family, model_name, max_comments)

    try:
        if model_family == "gemini":
            return run_lens_gemini(prompt, repo_dir, model=model_name)
        elif model_family == "codex":
            return run_lens_codex(prompt, repo_dir, model=model_name)
        else:
            review = run_lens_claude(prompt, repo_dir, max_turns, model=model_name)
            return review.text
    except subprocess.TimeoutExpired:
        log.error("Lens %s (%s) timed out after 300s", lens_name, model_family)
        return ""
