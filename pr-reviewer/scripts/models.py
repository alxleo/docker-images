"""AI model invocation: Claude, Gemini, Codex. Fully deterministic CLI calls."""

import json
import logging
import subprocess
import time
from pathlib import Path

from config import CLAUDE_REVIEW_TOOLS, PLUGIN_DIR, PLUGINS_DIR

log = logging.getLogger(__name__)


def _log_lens_result(model: str, result: subprocess.CompletedProcess, duration_s: float):
    """Log lens execution result for observability."""
    status = "ok" if result.returncode == 0 else f"exit={result.returncode}"
    stdout_len = len(result.stdout.strip())
    stderr_preview = result.stderr.strip()[:200] if result.stderr.strip() else ""
    log.info("Lens %s completed: %s, stdout=%d chars, %.1fs%s",
             model, status, stdout_len, duration_s,
             f", stderr={stderr_preview}" if stderr_preview else "")
    if result.returncode != 0:
        log.warning("Lens %s failed (exit %d): %s", model, result.returncode,
                    result.stderr.strip()[:500] or result.stdout.strip()[:500])


def run_lens_claude(prompt: str, repo_dir: Path, max_turns: int,
                    model: str = "sonnet") -> str:
    """Run review via Claude Code CLI. Fully deterministic invocation."""
    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--allowedTools", CLAUDE_REVIEW_TOOLS,
        "--max-turns", str(max_turns),
    ]
    if PLUGIN_DIR.is_dir() and (PLUGIN_DIR / ".claude-plugin").is_dir():
        cmd.extend(["--plugin-dir", str(PLUGIN_DIR)])
    if PLUGINS_DIR.is_dir():
        for plugin_dir in PLUGINS_DIR.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / ".claude-plugin").is_dir():
                cmd.extend(["--plugin-dir", str(plugin_dir)])
    start = time.time()
    log.info("Claude invocation: --model %s --max-turns %d", model, max_turns)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("claude", result, time.time() - start)
    if result.returncode != 0:
        return ""
    try:
        output = json.loads(result.stdout)
        return output.get("result", "")
    except json.JSONDecodeError:
        return result.stdout.strip()


def run_lens_gemini(prompt: str, repo_dir: Path, model: str = "gemini-2.5-pro") -> str:
    """Run review via Gemini CLI. Fully deterministic invocation."""
    cmd = ["gemini", "-p", "Review the code below. Follow the system instructions provided via stdin exactly.",
           "-m", model]
    start = time.time()
    log.info("Gemini invocation: -m %s", model)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("gemini", result, time.time() - start)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def run_lens_codex(prompt: str, repo_dir: Path, model: str = "o3") -> str:
    """Run review via Codex CLI. Fully deterministic invocation."""
    cmd = ["codex", "exec", "-m", model]
    start = time.time()
    log.info("Codex invocation: -m %s", model)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=300)
    _log_lens_result("codex", result, time.time() - start)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
