"""Context gathering: repomap (tree-sitter), impact analysis (ripgrep)."""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Top-level AST node types that represent definitions, by language
_DEFINITION_TYPES = {
    "function_definition", "class_definition", "decorated_definition",
    "function_declaration", "class_declaration", "method_definition",
    "interface_declaration", "type_alias_declaration", "enum_declaration",
    "struct_item", "impl_item", "fn_item", "enum_item", "trait_item",
}


def generate_repomap(repo_dir: Path, max_chars: int = 8000) -> str:
    """Generate a compact structural map of the repo using tree-sitter.

    Returns a text overview of top-level definitions per file, truncated to
    max_chars. Like a table of contents before reading the diff.
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
    max_files = 200

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


def analyze_impact(repo_dir: Path, diff: str, max_refs: int = 20) -> str:
    """Find files that reference each changed file. Cheap grep-based pre-pass.

    Returns a text summary like:
        scripts/foo.py: referenced by tests/test_foo.py, scripts/bar.py
    """
    changed_files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            changed_files.append(line[6:])

    if not changed_files:
        return ""

    impacts = []
    for filepath in changed_files:
        basename = Path(filepath).stem
        if not basename or basename.startswith("."):
            continue

        try:
            result = subprocess.run(
                ["rg", "-l", "--max-count=1", basename,
                 "--glob", f"!{filepath}",
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
