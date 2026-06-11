"""Meta lens: post-hoc review of specialist lens output for gaps."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import PROMPTS_DIR
from diff import preprocess_diff, shuffle_diff
from models import run_lens_claude
from verification import Finding, parse_findings

log = logging.getLogger(__name__)


def run_meta_lens(
    findings: list[Finding],
    diff: str,
    repo_dir: Path,
    config: dict[str, Any],
    commit_messages: str = "",
    pr_description: str = "",
    repomap: str = "",
    cross_file_context: str = "",
) -> list[Finding]:
    """Run the meta lens to find gaps in specialist lens coverage.

    Receives structured findings from all specialist lenses plus the original
    diff and context. Returns new findings for gaps the specialists missed.
    Runs as a separate claude -p call (not inside the orchestrator session).
    """
    meta_cfg = config.get("lenses", {}).get("meta", {})
    if not meta_cfg.get("enabled", False):
        return []

    # Build findings summary for the meta prompt
    if findings:
        summary_lines = []
        for f in findings:
            status = ""
            if not f.verified:
                status = " [unverified]"
            elif not f.in_diff:
                status = " [body-only]"
            summary_lines.append(
                f"- [{f.severity}] {f.file_path}:{f.line_num} — {f.title}{status}"
            )
        findings_summary = "\n".join(summary_lines)
    else:
        findings_summary = "No findings from specialist lenses."

    # Load and fill the meta prompt template
    meta_prompt_file = PROMPTS_DIR / "meta.md"
    if not meta_prompt_file.exists():
        log.warning("Meta prompt not found at %s", meta_prompt_file)
        return []

    preamble_file = PROMPTS_DIR / "_preamble.md"
    preamble = preamble_file.read_text() if preamble_file.exists() else ""

    meta_template = meta_prompt_file.read_text()
    max_comments = meta_cfg.get("max_comments", 3)
    meta_instructions = meta_template.replace(
        "{findings_summary}", findings_summary,
    ).replace(
        "{max_comments}", str(max_comments),
    )

    # Build context sections
    context = ""
    if pr_description:
        context += f"\n\n## PR Description\n\n{pr_description}"
    if commit_messages:
        context += f"\n\n## Commit Messages\n\n{commit_messages}"
    if repomap:
        context += f"\n\n## Repository Structure\n\n{repomap}"
    if cross_file_context:
        context += f"\n\n## Cross-File Context\n\n{cross_file_context}"

    processed_diff = preprocess_diff(diff)
    if config.get("shuffle_diff", True):
        processed_diff = shuffle_diff(processed_diff)

    prompt = (
        f"{preamble}\n\n{meta_instructions}\n\n---\n\n"
        f"Review this PR diff for gaps:{context}\n\n"
        f"```diff\n{processed_diff}\n```"
    )

    # Resolve model — meta defaults to opus
    model = meta_cfg.get("model", "opus")
    max_turns = 5

    log.info("Meta lens: running with model=%s, max_turns=%d, %d specialist findings as context",
             model, max_turns, len(findings))

    review = run_lens_claude(prompt, repo_dir, max_turns, model=model)
    if not review:
        log.info("Meta lens: no output (model=%s)", model)
        return []

    meta_findings = parse_findings(review.text, lens_name="meta")
    log.info("Meta lens: %d findings from %s (%.1fs, $%.4f)",
             len(meta_findings), model,
             review.duration_ms / 1000 if review.duration_ms else 0,
             review.cost_usd)
    return meta_findings
