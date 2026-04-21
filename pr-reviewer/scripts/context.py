"""Context gathering: repomap (tree-sitter + PageRank), impact analysis, LLM-planned searches."""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from config import PROMPTS_DIR

log = logging.getLogger(__name__)

# AST node types that represent definitions (any language)
_DEFINITION_TYPES = {
    "function_definition", "class_definition", "decorated_definition",
    "function_declaration", "class_declaration", "method_definition",
    "interface_declaration", "type_alias_declaration", "enum_declaration",
    "struct_item", "impl_item", "fn_item", "enum_item", "trait_item",
}

# Languages where tree-sitter structural parsing adds no value
_SKIP_LANGS = {"bash", "markdown", "toml", "yaml", "json", "dockerfile",
               "css", "html", "xml", "sql"}

# Directories to skip during file discovery
_SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv",
              "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", "egg-info",
              ".next", ".nuxt", "coverage", ".cache"}


def _has_tree_sitter() -> bool:
    """Check if tree-sitter dependencies are available."""
    try:
        import grep_ast  # used by _parse_file and _get_parser
        import tree_sitter_language_pack  # used by _get_parser
        import tree_sitter  # used by _get_parser
        return bool(grep_ast and tree_sitter_language_pack and tree_sitter)
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FileTags:
    """Definitions and references extracted from a single source file."""
    defs: dict[str, int]           # name → line number
    refs: set[str]                 # identifiers referenced but not defined here
    signatures: dict[str, str]     # name → first line of definition (for display)


def _walk_defs(node, code: bytes, defs: dict[str, int], sigs: dict[str, str]):
    """Recursively extract definition names, line numbers, and signatures."""
    actual = node
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in _DEFINITION_TYPES:
                actual = child
                break
        else:
            return
    if actual.type in _DEFINITION_TYPES - {"decorated_definition"}:
        name_node = actual.child_by_field_name("name")
        if name_node:
            name = name_node.text.decode(errors="replace")
            defs[name] = actual.start_point[0] + 1
            first_line = code[actual.start_byte:actual.end_byte].decode(errors="replace").split("\n")[0]
            sigs[name] = first_line.strip()
    # Recurse into children for nested defs (methods inside classes, etc.)
    for child in node.children:
        if child.type in (*_DEFINITION_TYPES, "decorated_definition"):
            _walk_defs(child, code, defs, sigs)
        elif child.type in ("block", "class_body", "declaration_list"):
            for gc in child.children:
                _walk_defs(gc, code, defs, sigs)


def _walk_identifiers(node, ids: set):
    """Collect all identifier names from the AST."""
    if node.type == "identifier":
        ids.add(node.text.decode(errors="replace"))
    for child in node.children:
        _walk_identifiers(child, ids)


def extract_file_tags(path: Path, lang, parser) -> FileTags | None:
    """Extract definitions and references from a single file via tree-sitter."""
    try:
        code = path.read_bytes()
        tree = parser.parse(code)
    except (OSError, ValueError) as _:
        return None

    defs: dict[str, int] = {}
    sigs: dict[str, str] = {}
    _walk_defs(tree.root_node, code, defs, sigs)

    all_ids: set[str] = set()
    _walk_identifiers(tree.root_node, all_ids)

    refs = all_ids - set(defs.keys())
    return FileTags(defs=defs, refs=refs, signatures=sigs)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _parse_changed_files(diff: str) -> list[str]:
    """Extract file paths from diff +++ headers."""
    return [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]


_PARSER_CACHE: dict[str, tuple | None] = {}


def _get_parser(lang_name: str) -> tuple | None:
    """Get (language, parser) for a language name, caching instances."""
    if lang_name in _PARSER_CACHE:
        return _PARSER_CACHE[lang_name]
    try:
        from tree_sitter_language_pack import get_language
        from tree_sitter import Parser
        lang = get_language(lang_name)
        parser = Parser(lang)
        _PARSER_CACHE[lang_name] = (lang, parser)
        return (lang, parser)
    except (ImportError, LookupError, OSError) as _:
        _PARSER_CACHE[lang_name] = None
        return None


def _parse_file(path: Path, repo_dir: Path) -> tuple[str, FileTags] | None:
    """Parse a single file, returning (rel_path, tags) or None."""
    try:
        from grep_ast import filename_to_lang
    except ImportError:
        return None
    rel = str(path.relative_to(repo_dir))
    lang_name = filename_to_lang(rel)
    if lang_name is None:
        return None
    if lang_name in _SKIP_LANGS:
        return None
    pair = _get_parser(lang_name)
    if not pair:
        return None
    lang, parser = pair
    tags = extract_file_tags(path, lang, parser)
    if not tags:
        return None
    return (rel, tags)


def _expand_related_files(
    repo_dir: Path, search_names: set[str],
    all_tags: dict[str, FileTags], max_expansion: int,
) -> None:
    """Find files referencing search_names via ripgrep and parse them."""
    if not search_names:
        return
    meaningful_names = [d for d in search_names if len(d) > 2]
    if not meaningful_names:
        return
    pattern = "|".join(re.escape(d) for d in meaningful_names[:80])
    try:
        rg = subprocess.run(
            ["rg", "-l", "--word-regexp", "-e", pattern,
             "--glob", "!*.lock", "--glob", "!*.min.*",
             "--glob", "!node_modules/**", "--glob", "!.git/**"],
            capture_output=True, text=True, cwd=repo_dir, timeout=15, check=False,
        )
        ref_files = [f for f in rg.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return

    parsed = 0
    for rel_path in ref_files:
        if rel_path in all_tags:
            continue
        abs_path = repo_dir / rel_path
        if not abs_path.is_file():
            continue
        result = _parse_file(abs_path, repo_dir)
        if result is None:
            continue
        rel, tags = result
        all_tags[rel] = tags
        parsed += 1
        if parsed >= max_expansion:
            break


def build_reference_graph(
    repo_dir: Path, changed_files: list[str], max_expansion: int = 200,
) -> tuple[dict[str, dict[str, float]], dict[str, FileTags]]:
    """Build a cross-file reference graph using two-pass bounded expansion.

    Pass 1: Parse diff files → collect definition names.
    Pass 2: ripgrep for files referencing those defs → parse those too.
    Returns (edges, all_tags) where edges[src][dst] = weight.
    """
    all_tags: dict[str, FileTags] = {}

    # Pass 1: parse files touched in the diff
    diff_defs: set[str] = set()
    diff_refs: set[str] = set()
    for rel_path in changed_files:
        abs_path = repo_dir / rel_path
        if not abs_path.is_file():
            continue
        result = _parse_file(abs_path, repo_dir)
        if result:
            rel, tags = result
            all_tags[rel] = tags
            diff_defs.update(tags.defs.keys())
            diff_refs.update(tags.refs)

    # Pass 2: find related files via ripgrep and parse (bounded expansion)
    _expand_related_files(repo_dir, diff_defs | diff_refs, all_tags, max_expansion)

    log.info("Repomap graph: %d files parsed (%d from diff, %d expanded)",
             len(all_tags), len(changed_files), max(0, len(all_tags) - len(changed_files)))

    # Build global def→file index
    def_to_file: dict[str, str] = {}
    for rel, tags in all_tags.items():
        for name in tags.defs:
            def_to_file[name] = rel

    # Build edges: file A refs a def in file B → edge A→B
    edges: dict[str, dict[str, float]] = {}
    for src, tags in all_tags.items():
        ref_counts: dict[str, int] = {}
        for ref_name in tags.refs:
            dst = def_to_file.get(ref_name)
            if dst and dst != src:
                ref_counts[dst] = ref_counts.get(dst, 0) + 1
        if ref_counts:
            edges[src] = {dst: math.sqrt(count) for dst, count in ref_counts.items()}
        else:
            # Self-loop to prevent PageRank starvation for isolated files
            edges[src] = {src: 0.1}

    return edges, all_tags


# ---------------------------------------------------------------------------
# PageRank
# ---------------------------------------------------------------------------

def pagerank(
    edges: dict[str, dict[str, float]],
    personalization: dict[str, float],
    damping: float = 0.85,
    iterations: int = 20,
) -> dict[str, float]:
    """Personalized PageRank via power iteration. No external dependencies."""
    nodes = set()
    for src, dsts in edges.items():
        nodes.add(src)
        nodes.update(dsts.keys())
    for node in personalization:
        nodes.add(node)
    nodes_list = sorted(nodes)
    n = len(nodes_list)
    if n == 0:
        return {}
    idx = {node: i for i, node in enumerate(nodes_list)}

    total_p = sum(personalization.get(node, 0.01) for node in nodes_list)
    p = [personalization.get(node, 0.01) / total_p for node in nodes_list]

    rank = list(p)
    for _ in range(iterations):
        new_rank = [(1 - damping) * p[i] for i in range(n)]
        for src, dsts in edges.items():
            si = idx.get(src)
            if si is None:
                continue
            total_weight = sum(dsts.values())
            if total_weight == 0:
                continue
            for dst, weight in dsts.items():
                di = idx.get(dst)
                if di is None:
                    continue
                new_rank[di] += damping * rank[si] * (weight / total_weight)
        rank = new_rank

    return {nodes_list[i]: rank[i] for i in range(n)}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_repomap(ranked_files: list[str], all_tags: dict[str, FileTags],
                   max_chars: int = 6000) -> str:
    """Render ranked files with their definition signatures, budget-capped."""
    lines = []
    total = 0
    for rel in ranked_files:
        tags = all_tags.get(rel)
        if tags is None:
            continue
        if not tags.signatures:
            continue
        tag_defs = tags.defs
        sorted_defs = sorted(tags.signatures.items(), key=lambda x: tag_defs.get(x[0], 0))
        file_block = f"{rel}\n" + "\n".join(f"  {sig}" for _, sig in sorted_defs) + "\n"
        if total + len(file_block) > max_chars:
            if lines:
                lines.append("...\n")
            break
        lines.append(file_block)
        total += len(file_block)
    return "".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_repomap(repo_dir: Path, diff: str = "", max_chars: int = 6000) -> str:
    """Generate a diff-personalized structural map of the repo.

    Uses tree-sitter to extract definitions and references, builds a cross-file
    reference graph, and runs personalized PageRank biased toward files in the
    diff. Returns a budget-capped overview of the most relevant files and their
    definitions — a subway map, not a phone book.

    When diff is empty, falls back to a simple alphabetical listing.
    """
    if not _has_tree_sitter():
        log.info("grep-ast not installed — skipping repomap")
        return ""

    changed_files = _parse_changed_files(diff) if diff else []

    if not changed_files:
        return _generate_repomap_simple(repo_dir, max_chars)

    start = time.time()
    edges, all_tags = build_reference_graph(repo_dir, changed_files)

    if not all_tags:
        # No parseable files in the diff (e.g., YAML-only PR) — fall back to simple listing
        log.info("Repomap: no parseable files in diff, falling back to simple listing")
        return _generate_repomap_simple(repo_dir, max_chars)

    # Personalization: high weight for diff files, medium for 1-hop, low for rest
    personalization: dict[str, float] = {}
    for f in changed_files:
        if f in all_tags:
            personalization[f] = 1.0
    one_hop = set()
    for f in changed_files:
        for dst in edges.get(f, {}):
            one_hop.add(dst)
        for src, dsts in edges.items():
            if f in dsts:
                one_hop.add(src)
    for f in one_hop:
        if f not in personalization:
            personalization[f] = 0.15

    ranks = pagerank(edges, personalization)
    ranked_files = sorted(ranks.keys(), key=lambda f: -ranks[f])

    result = render_repomap(ranked_files, all_tags, max_chars)
    log.info("Repomap: %d chars, %d files ranked in %.1fs",
             len(result), len(ranked_files), time.time() - start)
    return result


def _generate_repomap_simple(repo_dir: Path, max_chars: int) -> str:
    """Fallback: alphabetical listing when no diff is provided."""
    lines = []
    total = 0
    count = 0
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(repo_dir))
        path_parts = Path(rel).parts
        hidden = any(part.startswith(".") for part in path_parts)
        skipped = bool(set(path_parts) & _SKIP_DIRS)
        if any((hidden, skipped)):
            continue
        result = _parse_file(path, repo_dir)
        if not result:
            continue
        rel, tags = result
        if not tags.signatures:
            continue
        tag_defs = tags.defs
        sorted_defs = sorted(tags.signatures.items(), key=lambda x: tag_defs.get(x[0], 0))
        file_block = f"{rel}\n" + "\n".join(f"  {sig}" for _, sig in sorted_defs) + "\n"
        if total + len(file_block) > max_chars:
            lines.append("...\n")
            break
        lines.append(file_block)
        total += len(file_block)
        count += 1
        if count >= 200:
            break
    return "".join(lines)




def _run_planner(prompt: str, repo_dir: Path) -> list[dict]:
    """Run a single planner prompt via haiku. Returns list of query dicts."""
    cmd = [
        "claude", "-p",
        "--model", "haiku",
        "--output-format", "json",
        "--allowedTools", "",
        "--max-turns", "1",
    ]
    try:
        start = time.time()
        result = subprocess.run(cmd, input=prompt, capture_output=True,
                                text=True, cwd=repo_dir, timeout=90, check=False)
        log.info("Search planner completed in %.1fs", time.time() - start)

        if result.returncode != 0:
            log.warning("Search planner failed (exit %d)", result.returncode)
            return []

        output = json.loads(result.stdout)
        raw_result = output.get("result", "")

        json_match = re.search(r'\[.*\]', raw_result, re.DOTALL)
        if not json_match:
            return []
        queries = json.loads(json_match.group())
        return queries if isinstance(queries, list) else []

    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError) as e:
        log.warning("Search planner error: %s", e)
        return []


def _deduplicate_queries(queries: list[dict], max_queries: int = 12) -> list[dict]:
    """Deduplicate queries by pattern and cap total count."""
    seen_patterns: set[str] = set()
    unique: list[dict] = []
    for q in queries:
        pattern = q.get("pattern", "")
        if not pattern or pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        unique.append(q)
        if len(unique) >= max_queries:
            break
    return unique


def plan_searches(diff: str, repo_dir: Path, config: dict[str, Any]) -> str:
    """Use a fast LLM to generate targeted search queries, execute them, return context.

    Runs one or two planner prompts (category-based and symbol-centric) via haiku,
    deduplicates the queries, then executes them as ripgrep searches.
    """
    if not config.get("planned_searches", True):
        return ""

    diff_snippet = diff[:8000]

    # Category planner (original)
    categories_file = PROMPTS_DIR / "_planner_categories.md"
    if not categories_file.exists():
        log.warning("Category planner prompt not found at %s", categories_file)
        return ""

    categories_prompt = f"{categories_file.read_text()}\n\nDiff:\n```\n{diff_snippet}\n```"
    queries = _run_planner(categories_prompt, repo_dir)

    # Symbol planner (dual planner mode)
    if config.get("dual_planner", True):
        symbols_file = PROMPTS_DIR / "_planner_symbols.md"
        if symbols_file.exists():
            symbols_prompt = f"{symbols_file.read_text()}\n\nDiff:\n```\n{diff_snippet}\n```"
            symbol_queries = _run_planner(symbols_prompt, repo_dir)
            queries = _deduplicate_queries(queries + symbol_queries)
            log.info("Dual planner: %d queries after dedup", len(queries))
        else:
            log.warning("Symbol planner prompt not found at %s", symbols_file)

    if not queries:
        return ""

    context_lines: list[str] = []
    for query in queries[:12]:
        pattern = query.get("pattern", "")
        category = query.get("category", "")
        rationale = query.get("rationale", "")
        if not pattern:
            continue

        try:
            rg = subprocess.run(
                ["rg", "-e", pattern, "-n", "--max-count=3", "--max-columns=200",
                 "--glob", "!*.lock", "--glob", "!*.min.*"],
                capture_output=True, text=True, cwd=repo_dir, timeout=5, check=False,
            )
            matches = rg.stdout.strip()
            if matches:
                match_lines = matches.splitlines()[:10]
                context_lines.append(
                    f"### {category}: {rationale}\n"
                    f"Pattern: `{pattern}`\n"
                    + "\n".join(match_lines)
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    if not context_lines:
        return ""

    log.info("Planned searches: %d queries, %d with results", len(queries), len(context_lines))
    return "Cross-file context (LLM-planned searches):\n\n" + "\n\n".join(context_lines)
