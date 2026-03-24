"""Prompt assembly: loads preamble + lens template, adds context sections."""

from config import PROMPTS_DIR
from diff import preprocess_diff


def build_review_prompt(lens_name: str, diff: str, max_comments: int,
                        commit_messages: str = "", pr_description: str = "",
                        repomap: str = "", impact: str = "",
                        cross_file_context: str = "") -> str:
    """Build the full review prompt from preamble + lens template + context + diff."""
    prompt_file = PROMPTS_DIR / f"{lens_name}.md"
    if not prompt_file.exists():
        return ""

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
    if cross_file_context:
        context += f"\n\n## Cross-File Context\n\n{cross_file_context}"

    processed_diff = preprocess_diff(diff)

    return (f"{preamble}\n\n{lens_instructions}\n\n---\n\n"
            f"Review this PR diff:{constraint}{context}\n\n```diff\n{processed_diff}\n```")
