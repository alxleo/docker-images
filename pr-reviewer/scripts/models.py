"""AI model invocation: Claude, Gemini, Codex. Fully deterministic CLI calls."""

import dataclasses
import json
import logging
import subprocess
import time
from pathlib import Path

from config import CLAUDE_REVIEW_TOOLS, PLUGIN_DIR, PLUGINS_DIR, STATE_DIR

log = logging.getLogger(__name__)


@dataclasses.dataclass
class ReviewResult:
    """Structured result from a Claude review invocation."""
    text: str
    session_id: str = ""
    num_turns: int = 0
    max_turns: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str = ""

    def __bool__(self):
        return bool(self.text and self.text.strip())

    def summary(self) -> str:
        tokens_in = f"{self.input_tokens // 1000}k" if self.input_tokens >= 1000 else str(self.input_tokens)
        tokens_out = f"{self.output_tokens // 1000}k" if self.output_tokens >= 1000 else str(self.output_tokens)
        return (f"session={self.session_id[:12]} turns={self.num_turns}/{self.max_turns} "
                f"cost=${self.cost_usd:.2f} tokens={tokens_in}\u2192{tokens_out} "
                f"duration={self.duration_ms // 1000}s stop={self.stop_reason}")


def _save_session_metadata(session_id: str, raw_json: dict):
    """Persist full Claude JSON response for post-mortem debugging."""
    if not session_id:
        return
    session_dir = STATE_DIR / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / f"{session_id}.json").write_text(json.dumps(raw_json, indent=2))


def _parse_claude_json(stdout: str, max_turns: int) -> ReviewResult:
    """Parse Claude CLI JSON output into ReviewResult."""
    try:
        output = json.loads(stdout)
    except json.JSONDecodeError:
        return ReviewResult(text=stdout.strip())

    usage = output.get("usage", {})
    return ReviewResult(
        text=output.get("result", ""),
        session_id=output.get("session_id", ""),
        num_turns=output.get("num_turns", 0),
        max_turns=max_turns,
        cost_usd=output.get("total_cost_usd", 0.0),
        duration_ms=output.get("duration_ms", 0),
        input_tokens=usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        model=output.get("model", ""),
        stop_reason=output.get("stop_reason", ""),
    )


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
                    model: str = "sonnet") -> ReviewResult:
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
    # Timeout scales with max_turns: 60s per turn, minimum 300s
    timeout = max(300, max_turns * 60)
    start = time.time()
    log.info("Claude invocation: --model %s --max-turns %d --timeout %ds", model, max_turns, timeout)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=repo_dir, timeout=timeout)
    _log_lens_result("claude", result, time.time() - start)
    if result.returncode != 0:
        return ReviewResult(text="", max_turns=max_turns)
    review = _parse_claude_json(result.stdout, max_turns)
    log.info("Claude review: %s", review.summary())
    _save_session_metadata(review.session_id, json.loads(result.stdout))
    return review


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
