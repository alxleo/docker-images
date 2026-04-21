"""Post-processing pipeline: parse, verify, score, and render review findings."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Regex: strict format from lens output
_STRICT_PATTERN = re.compile(
    r'^###\s+\[(?P<severity>CRITICAL|HIGH|MEDIUM|LOW)\]\s+'
    r'\[(?P<file>[^:\]]+):(?P<line>\d+)\]\s*(?P<title>.*)',
    re.MULTILINE,
)

# Relaxed fallback: handles bold, missing brackets, backtick-wrapped paths
_RELAXED_PATTERN = re.compile(
    r'^(?:##|###)\s+(?:\*?\*?\[?(?P<severity>CRITICAL|HIGH|MEDIUM|LOW)\]?\*?\*?\s+)?'
    r'(?:`)?(?P<file>[^:\]`\n]+):(?P<line>\d+)(?:`)?'
    r'\s*(?P<title>.*)',
    re.MULTILINE,
)

# Cross-file claims: "also called in path/to/file", "see src/foo.py", etc.
_CROSS_FILE_CLAIM = re.compile(
    r'(?:also\s+(?:called|used|imported|referenced)\s+in|callers?\s+in|see\s+)'
    r'\s+[`"]?(?P<path>[a-zA-Z0-9_./-]+\.\w+)[`"]?',
    re.IGNORECASE,
)


@dataclasses.dataclass
class Finding:
    """A single review finding extracted from lens output."""

    severity: str
    file_path: str
    line_num: int
    title: str
    body: str
    lens: str = ""
    verified: bool = True
    in_diff: bool = True
    verification_log: str = ""
    confidence_score: float = -1  # -1 = unscored
    has_suggestion: bool = False


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_findings(body: str, lens_name: str = "") -> list[Finding]:
    """Extract structured Finding objects from raw lens markdown output."""
    matches = list(_STRICT_PATTERN.finditer(body))
    used_relaxed = False

    if not matches:
        matches = list(_RELAXED_PATTERN.finditer(body))
        if matches:
            used_relaxed = True
            log.info("parse_findings: strict missed, relaxed matched %d", len(matches))
        else:
            log.info("parse_findings: 0 findings in %d chars", len(body))
            return []

    if not used_relaxed:
        log.info("parse_findings: %d findings (strict)", len(matches))

    findings: list[Finding] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        finding_body = body[start:end].strip()

        findings.append(Finding(
            severity=match.group("severity") or "MEDIUM",
            file_path=match.group("file").lstrip("./"),
            line_num=int(match.group("line")),
            title=match.group("title").strip(),
            body=finding_body,
            lens=lens_name,
            has_suggestion="```suggestion" in finding_body,
        ))

    return findings


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def _build_diff_lines(diff: str) -> set[tuple[str, int]]:
    """Build set of (file, line_num) present in the diff (post-diff state)."""
    diff_lines: set[tuple[str, int]] = set()
    current_file = None
    current_line = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].lstrip("./")
        elif line.startswith("@@ "):
            m = re.search(r'\+(\d+)', line)
            if m:
                current_line = int(m.group(1))
        elif current_file:
            if line.startswith(("+", " ")):
                diff_lines.add((current_file, current_line))
                current_line += 1
            elif line.startswith("-"):
                pass  # deletions don't increment post-diff line
    return diff_lines


def _find_nearest_diff_line(file_path: str, line_num: int,
                            diff_lines: set[tuple[str, int]]) -> int | None:
    """Search +/-5 lines for the nearest line present in the diff."""
    for offset in range(1, 6):
        for candidate in (line_num + offset, line_num - offset):
            if (file_path, candidate) in diff_lines:
                return candidate
    return None


def verify_findings(findings: list[Finding], diff: str,
                    repo_dir: Path) -> list[Finding]:
    """Verify each finding against actual code. Mutates findings in-place.

    - Checks if file:line is present in the diff (downgrades to body-only if not)
    - Checks if file exists in the checkout
    - Spot-checks cross-file claims
    - Validates suggestion block context
    """
    if not findings:
        return findings

    diff_lines = _build_diff_lines(diff)
    verified_count = 0
    downgraded_count = 0
    log_entries: list[str] = []

    for f in findings:
        checks: list[str] = []

        # Check 1: Diff presence
        if (f.file_path, f.line_num) in diff_lines:
            checks.append("diff: exact match")
        else:
            nearest = _find_nearest_diff_line(f.file_path, f.line_num, diff_lines)
            if nearest is not None:
                checks.append(f"diff: adjusted {f.line_num}->{nearest}")
                f.line_num = nearest
            else:
                f.in_diff = False
                downgraded_count += 1
                checks.append("diff: NOT found (downgraded to body-only)")

        # Check 2: File/line existence in checkout
        try:
            file_path = repo_dir / f.file_path
            if not file_path.exists():
                f.verified = False
                checks.append("file: NOT found in checkout")
            elif file_path.is_file():
                lines = file_path.read_text(errors="replace").splitlines()
                if f.line_num > len(lines):
                    f.verified = False
                    checks.append(f"line: {f.line_num} > EOF ({len(lines)} lines)")
                else:
                    checks.append("file: exists, line valid")
        except OSError as e:
            f.verified = False
            checks.append(f"file: read error ({e})")

        # Check 3: Cross-file claim spot-check
        for claim_match in _CROSS_FILE_CLAIM.finditer(f.body):
            claimed_path = claim_match.group("path")
            claimed_full = repo_dir / claimed_path
            if claimed_full.exists():
                checks.append(f"xref: {claimed_path} exists")
            else:
                checks.append(f"xref: {claimed_path} NOT found")

        # Check 4: Suggestion block validation
        if f.has_suggestion:
            _validate_suggestion(f, repo_dir, checks)

        f.verification_log = "; ".join(checks)
        if f.in_diff and f.verified:
            verified_count += 1
        log_entries.append(f"  {f.file_path}:{f.line_num} — {f.verification_log}")

    log.info("verify_findings: %d/%d verified, %d downgraded to body-only",
             verified_count, len(findings), downgraded_count)
    for entry in log_entries:
        log.info(entry)

    return findings


def _validate_suggestion(finding: Finding, repo_dir: Path,
                         checks: list[str]) -> None:
    """Check that a suggestion block's replaced content matches actual code."""
    suggestion_match = re.search(
        r'```suggestion\n(.*?)```',
        finding.body,
        re.DOTALL,
    )
    if not suggestion_match:
        return

    try:
        file_path = repo_dir / finding.file_path
        if not file_path.is_file():
            return
        lines = file_path.read_text(errors="replace").splitlines()
        if finding.line_num <= len(lines):
            # The suggestion replaces the line at finding.line_num.
            # We can't fully validate without knowing the exact before-content
            # the LLM intended to replace, but we can confirm the line exists
            # and isn't empty (a sign the reference is valid).
            actual_line = lines[finding.line_num - 1]  # 1-indexed
            if actual_line.strip():
                checks.append("suggestion: target line exists")
            else:
                checks.append("suggestion: target line is blank (may be misaligned)")
    except OSError as e:
        checks.append(f"suggestion: read error ({e})")


# ---------------------------------------------------------------------------
# Score (haiku)
# ---------------------------------------------------------------------------

def score_findings(findings: list[Finding], repo_dir: Path,
                   config: dict[str, Any],
                   scoring_model: str | None = None) -> list[Finding]:
    """Score findings via LLM, apply threshold + total cap.

    Returns filtered list. Findings below scoring_threshold are dropped.
    Total cap applied, but findings >= scoring_exempt_threshold bypass it.
    """
    if not findings:
        return findings

    threshold = config.get("scoring_threshold", 6)
    total_cap = config.get("max_total_comments", 7)
    exempt_threshold = config.get("scoring_exempt_threshold", 9)

    # Build prompt with numbered findings
    numbered = []
    for i, f in enumerate(findings):
        numbered.append(
            f"[{i}] [{f.severity}] {f.file_path}:{f.line_num} — {f.title}\n"
            f"{f.body[:500]}"  # truncate body to control token usage
        )
    findings_text = "\n\n".join(numbered)

    prompt = (
        "Score each code review finding below on 0-10. Evaluate:\n"
        "1. Evidence: Does the finding cite specific code? (0=speculative, 10=proven)\n"
        "2. Actionable: Is the fix concrete? (0=vague 'consider...', 10=exact code change)\n"
        "3. Useful: Would a senior engineer value this? (0=obvious/noisy, 10=subtle real bug)\n\n"
        "Return ONLY a JSON array, no markdown:\n"
        '[{"index": 0, "score": 7, "reason": "brief"}, ...]\n\n'
        f"Findings:\n\n{findings_text}"
    )

    model = scoring_model or config.get("scoring_model", "haiku")
    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--allowedTools", "",
        "--max-turns", "1",
    ]

    try:
        start = time.time()
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            cwd=repo_dir, timeout=60, check=False,
        )
        elapsed = time.time() - start
        log.info("score_findings: %s completed in %.1fs", model, elapsed)

        if result.returncode != 0:
            log.warning("score_findings: haiku failed (exit %d), passing all findings through",
                        result.returncode)
            return _apply_total_cap(findings, total_cap, exempt_threshold)

        output = json.loads(result.stdout)
        if not isinstance(output, dict):
            log.warning("score_findings: unexpected haiku JSON shape (%s), passing through",
                        type(output).__name__)
            return _apply_total_cap(findings, total_cap, exempt_threshold)

        raw_result = output.get("result", "")

        json_match = re.search(r'\[.*\]', raw_result, re.DOTALL)
        if not json_match:
            log.warning("score_findings: no JSON array in haiku output, passing through")
            return _apply_total_cap(findings, total_cap, exempt_threshold)

        scores = json.loads(json_match.group())
        if not isinstance(scores, list):
            log.warning("score_findings: scores is %s not list, passing through",
                        type(scores).__name__)
            return _apply_total_cap(findings, total_cap, exempt_threshold)

    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError) as e:
        log.warning("score_findings: error (%s), passing all findings through", e)
        return _apply_total_cap(findings, total_cap, exempt_threshold)

    # Apply scores to findings
    score_map: dict[int, tuple[float, str]] = {}
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index", -1)
        score = entry.get("score", -1)
        reason = entry.get("reason", "")
        if 0 <= idx < len(findings) and isinstance(score, (int, float)):
            score_map[idx] = (float(score), reason)

    scored_findings: list[Finding] = []
    dropped = 0
    for i, f in enumerate(findings):
        if i in score_map:
            f.confidence_score = score_map[i][0]
            reason = score_map[i][1]
            if f.confidence_score < threshold:
                log.info("Score: %s:%d — %.0f/10 DROPPED (%s)",
                         f.file_path, f.line_num, f.confidence_score, reason)
                dropped += 1
                continue
            log.info("Score: %s:%d — %.0f/10 (%s)",
                     f.file_path, f.line_num, f.confidence_score, reason)
        else:
            # Haiku didn't score this finding — keep it (fail-open)
            log.info("Score: %s:%d — unscored (keeping)", f.file_path, f.line_num)
        scored_findings.append(f)

    log.info("score_findings: %d kept, %d dropped (threshold=%d)",
             len(scored_findings), dropped, threshold)

    return _apply_total_cap(scored_findings, total_cap, exempt_threshold)


def _apply_total_cap(findings: list[Finding], total_cap: int,
                     exempt_threshold: float) -> list[Finding]:
    """Apply cross-lens total comment cap. Findings scored >= exempt_threshold bypass it."""
    if total_cap <= 0 or len(findings) <= total_cap:
        return findings

    # Split into exempt (high-confidence) and cappable
    exempt = [f for f in findings if f.confidence_score >= exempt_threshold]
    cappable = [f for f in findings if f.confidence_score < exempt_threshold]

    # Sort cappable by severity (best first), then score as tiebreaker
    cappable.sort(key=lambda f: (
        _SEVERITY_ORDER.get(f.severity, 99),
        -f.confidence_score if f.confidence_score >= 0 else 0,
    ))

    # Keep top N from cappable, plus all exempt
    remaining_cap = max(0, total_cap - len(exempt))
    kept = cappable[:remaining_cap]
    dropped_count = len(cappable) - remaining_cap

    result = exempt + kept

    log.info("Cap: keeping %d/%d findings (total_cap=%d, %d exempt, %d dropped)",
             len(result), len(findings), total_cap, len(exempt), dropped_count)

    return result


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_findings(findings: list[Finding]) -> str:
    """Reconstruct markdown from Finding objects."""
    if not findings:
        return ""

    parts: list[str] = []
    for f in findings:
        header = f"### [{f.severity}] [{f.file_path}:{f.line_num}] {f.title}"
        if f.body:
            parts.append(f"{header}\n\n{f.body}")
        else:
            parts.append(header)

    return "\n\n".join(parts)
