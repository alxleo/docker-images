"""Shared review engine — re-exports from focused modules.

This facade preserves backwards compatibility for gh_watcher.py,
gitea_webhook.py, and tests that import from review_core.

Domain modules:
  config.py       — paths, constants, secrets, state, lens selection, command parsing
  prompts.py      — prompt assembly from .md templates
  models.py       — AI CLI invocation (Claude, Gemini, Codex)
  routing.py      — diff relevance analysis, lens dispatch
  orchestrator.py — single-session orchestration with sub-agents
  diff.py         — diff preprocessing, shuffle
  context.py      — repomap (PageRank-ranked, tree-sitter), LLM-planned searches
  output.py       — inline comment parsing, severity capping
"""

# Re-export everything that consumers use via `import review_core as core`

# config.py
from config import (  # noqa: F401
    CONFIG_PATH, STATE_DIR, REPOS_DIR, PROMPTS_DIR,
    PLUGINS_DIR, PLUGIN_DIR,
    COMMANDS, VALID_MODELS, LENS_ICONS, DEFAULT_MODEL,
    DEFAULT_MODELS, CLAUDE_REVIEW_TOOLS,
    load_config, read_secret,
    resolve_model as _resolve_model,
    load_state, save_state,
    enabled_lenses,
    parse_command,
)

# prompts.py
from prompts import build_review_prompt  # noqa: F401

# models.py
from models import (  # noqa: F401
    run_lens_claude, run_lens_gemini, run_lens_codex,
    _log_lens_result,
)

# routing.py
from routing import (  # noqa: F401
    analyze_diff_relevance, run_lens,
)

# orchestrator.py
from orchestrator import run_review_orchestrated  # noqa: F401

# diff.py
from diff import preprocess_diff, shuffle_diff  # noqa: F401

# context.py
from context import generate_repomap, plan_searches  # noqa: F401

# output.py
from output import parse_inline_comments, cap_by_severity  # noqa: F401

# verification.py
from verification import (  # noqa: F401
    Finding, parse_findings, verify_findings, score_findings, render_findings,
)

# meta.py
from meta import run_meta_lens  # noqa: F401
