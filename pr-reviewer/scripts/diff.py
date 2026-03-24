"""Diff preprocessing: strip delete-only files, language annotations, token budget, shuffle."""

import random
import re

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
    """
    if not raw_diff.strip():
        return raw_diff

    files: list[tuple[str, str]] = []
    current_file = ""
    current_lines: list[str] = []

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

    if not files:
        return raw_diff

    processed = []
    for filename, diff_text in files:
        has_additions = any(
            line.startswith("+") and not line.startswith("+++")
            for line in diff_text.splitlines()
        )
        if not has_additions:
            continue

        ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        lang = _EXT_TO_LANG.get(ext.lower(), "")
        if "dockerfile" in filename.lower():
            lang = "Dockerfile"
        header = f"## {filename}" + (f" [{lang}]" if lang else "") + "\n"
        processed.append((filename, header + diff_text))

    total_chars = sum(len(d) for _, d in processed)
    token_estimate = total_chars // 4

    if token_estimate > max_tokens:
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


def shuffle_diff(raw_diff: str) -> str:
    """Shuffle file order in a unified diff to break positional bias.

    Handles both raw diffs (split on `diff --git`) and preprocessed diffs
    (split on `## filename` headers from preprocess_diff).
    """
    if "\n## " in raw_diff or raw_diff.startswith("## "):
        sections = re.split(r'(?=^## )', raw_diff, flags=re.MULTILINE)
        sections = [s for s in sections if s.strip()]
        if len(sections) <= 1:
            return raw_diff
        random.shuffle(sections)
        return "\n".join(sections)

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
