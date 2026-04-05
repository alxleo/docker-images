"""Orchestrated review: single Claude session spawns lens sub-agents."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import DEFAULT_MODEL, PROMPTS_DIR, resolve_model
from diff import build_change_manifest
from models import run_lens_claude
from routing import run_lens

log = logging.getLogger(__name__)


def run_review_orchestrated(lenses: list[dict[str, Any]], diff: str, repo_dir: Path, config: dict[str, Any],
                            commit_messages: str = "", pr_description: str = "",
                            model_override: str | None = None, repomap: str = "",
                            depth: str = "standard", impact: str = "",
                            cross_file_context: str = "",
                            base_branch: str = "main") -> list[tuple[str, str]]:
    """Run multiple lenses in a single Claude session via sub-agents.

    Instead of N × claude -p (one per lens), this runs one orchestrator session
    that spawns each lens as a sub-agent via the Agent tool.

    For non-Claude models, falls back to individual run_lens() calls.

    Returns list of (lens_name, result) tuples for findings.
    """
    claude_lenses = []
    other_lenses = []
    for lens in lenses:
        lens_model = model_override
        if not lens_model:
            lens_model = config.get("lenses", {}).get(lens["name"], {}).get("model", "")
        if not lens_model:
            lens_model = config.get("default_model", DEFAULT_MODEL)
        if lens_model in ("gemini", "codex"):
            other_lenses.append(lens)
        else:
            claude_lenses.append(lens)

    results = []

    if claude_lenses:
        model_name = resolve_model(config, "claude", depth)
        base_turns = 25 if depth == "deep" else 15
        diff_lines = len(diff.splitlines()) if isinstance(diff, str) else 0
        multiplier = config.get("context", {}).get("max_turns_multiplier", 1.5)
        max_turns = int(base_turns * multiplier) if diff_lines > 500 else base_turns
        lens_names = [lens["name"] for lens in claude_lenses]

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
        if cross_file_context:
            context += f"\n\n## Cross-File Context\n\n{cross_file_context}"

        manifest, _ = build_change_manifest(diff)

        orchestrator_prompt = f"""{preamble}

You are a PR review orchestrator. Spawn specialized review agents to investigate this PR.

## Changed Files

{manifest}

## How to Investigate

Each agent has the full repository checkout (PR branch).
- Read any file: use the Read tool
- See what changed in a file: `git diff {base_branch}...HEAD -- <file>`
- See full diff: `git diff {base_branch}...HEAD`
- Check history: `git log --oneline -5 -- <file>`
- Search the repo: use Grep tool or `sg` (ast-grep)

CRITICAL: Do NOT reason about code from memory or assumptions. Read the actual file before flagging.
{context}

For each of the following lenses, spawn the corresponding agent using the Agent tool:
{chr(10).join(f'- **{name}** → spawn agent `pr-reviewer-lenses:{name}-lens`' for name in lens_names)}

Pass each agent the changed files manifest and investigation instructions above.
After all agents complete, output ALL findings combined verbatim. CRITICAL: preserve the exact `### [SEVERITY] [file:line]` format from each agent — do not summarize, reformat, add headers, or wrap findings. Just concatenate agent outputs. If an agent found nothing, skip it silently."""

        log.info("Orchestrated review: %d Claude lenses via single session (model=%s, max_turns=%d)",
                 len(claude_lenses), model_name, max_turns)

        review = run_lens_claude(orchestrator_prompt, repo_dir, max_turns, model=model_name)
        if review:
            label = lens_names[0] if len(lens_names) == 1 else "review"
            results.append((label, review.text))

    for lens in other_lenses:
        result = run_lens(lens, diff, repo_dir, config,
                          commit_messages=commit_messages,
                          pr_description=pr_description,
                          model_override=model_override,
                          repomap=repomap, depth=depth, impact=impact,
                          cross_file_context=cross_file_context)
        if result and result.strip():
            results.append((lens["name"], result))

    return results
