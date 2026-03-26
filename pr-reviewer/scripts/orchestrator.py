"""Orchestrated review: single Claude session spawns lens sub-agents."""

import logging
from pathlib import Path

from config import DEFAULT_MODEL, PROMPTS_DIR, resolve_model
from diff import preprocess_diff, shuffle_diff
from models import run_lens_claude
from routing import run_lens

log = logging.getLogger(__name__)


def run_review_orchestrated(lenses: list[dict], diff: str, repo_dir: Path, config: dict,
                            commit_messages: str = "", pr_description: str = "",
                            model_override: str | None = None, repomap: str = "",
                            depth: str = "standard", impact: str = "",
                            cross_file_context: str = "") -> list[tuple[str, str]]:
    """Run multiple lenses in a single Claude session via sub-agents.

    Instead of N × claude -p (one per lens), this runs one orchestrator session
    that spawns each lens as a sub-agent via the Agent tool.

    For non-Claude models, falls back to individual run_lens() calls.

    Returns list of (lens_name, result) tuples for findings.
    """
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

    if claude_lenses:
        model_name = resolve_model(config, "claude", depth)
        base_turns = 20 if depth == "deep" else 10
        diff_lines = len(diff.splitlines()) if isinstance(diff, str) else 0
        multiplier = config.get("context", {}).get("max_turns_multiplier", 1.5)
        max_turns = int(base_turns * multiplier) if diff_lines > 500 else base_turns
        lens_names = [l["name"] for l in claude_lenses]

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

        processed_diff = preprocess_diff(diff)
        if config.get("shuffle_diff", True):
            processed_diff = shuffle_diff(processed_diff)

        orchestrator_prompt = f"""{preamble}

You are a PR review orchestrator. Your job is to spawn specialized review agents and collect their findings.

For each of the following lenses, spawn the corresponding agent using the Agent tool:
{chr(10).join(f'- **{name}** → spawn agent `pr-reviewer-lenses:{name}-lens`' for name in lens_names)}

Pass each agent the PR diff below as its task. Collect all findings.

After all agents complete, output ALL findings combined verbatim. CRITICAL: preserve the exact `### [SEVERITY] [file:line]` format from each agent — do not summarize, reformat, add headers, or wrap findings. Just concatenate agent outputs. If an agent found nothing, skip it silently.
{context}

## PR Diff

```diff
{processed_diff}
```"""

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
