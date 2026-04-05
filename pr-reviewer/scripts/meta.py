"""Meta lens: opus-powered second opinion on what specialist lenses missed."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import PROMPTS_DIR, resolve_model
from diff import build_change_manifest
from models import run_lens_claude

log = logging.getLogger(__name__)


def run_meta_lens(findings: list[Any], diff: str, repo_dir: Path,
                  config: dict[str, Any], base_branch: str = "main") -> str:
    """Run meta lens review. Returns raw findings text or empty string."""
    meta_cfg = config.get("lenses", {}).get("meta", {})
    if not meta_cfg.get("enabled", False):
        return ""

    prompt_file = PROMPTS_DIR / "meta.md"
    preamble_file = PROMPTS_DIR / "_preamble.md"
    if not prompt_file.exists():
        log.warning("Meta lens prompt not found at %s", prompt_file)
        return ""

    preamble = preamble_file.read_text() if preamble_file.exists() else ""
    meta_instructions = prompt_file.read_text()
    manifest, _ = build_change_manifest(diff)

    # Summarize existing findings so meta lens knows what's already been flagged
    existing_summary = ""
    if findings:
        lines = [f"- [{f.severity}] {f.file_path}:{f.line_num} — {f.title}" for f in findings]
        existing_summary = (
            "\n\n## Already Flagged by Specialist Lenses\n\n"
            "Do NOT re-flag these issues. Focus on what was missed.\n\n"
            + "\n".join(lines)
        )

    prompt = f"""{preamble}

{meta_instructions}

## Changed Files

{manifest}

## How to Investigate

- Read any file: use the Read tool
- See what changed: `git diff {base_branch}...HEAD -- <file>`
- Check history: `git log --oneline -5 -- <file>`
- Search the repo: use Grep tool or `sg` (ast-grep)
{existing_summary}"""

    model = resolve_model(config, meta_cfg.get("model", "claude"), "deep")
    max_turns = 20
    max_comments = meta_cfg.get("max_comments", 3)

    log.info("Meta lens: running via %s (max_turns=%d, max_comments=%d)",
             model, max_turns, max_comments)

    result = run_lens_claude(prompt, repo_dir, max_turns, model=model)
    return result.text if result else ""
