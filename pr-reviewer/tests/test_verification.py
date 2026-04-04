"""Tests for verification.py — parse, verify, score, render pipeline."""

from __future__ import annotations

import json
from unittest.mock import patch

from verification import (
    Finding,
    parse_findings,
    verify_findings,
    score_findings,
    render_findings,
    _build_diff_lines,
    _apply_total_cap,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,8 @@ def login(user, password):
     if not user:
         return False
+    token = generate_token(user)
+    log.info("Token: %s", token)
     return True
"""

SAMPLE_FINDING = """\
### [HIGH] [src/auth.py:12] Secret in log output

**What:** Token is logged at INFO level.
**Why:** Secrets in logs leak to log aggregators.
**Fix:** Remove the token from the log statement.
"""

SAMPLE_FINDING_WITH_SUGGESTION = """\
### [HIGH] [src/auth.py:13] Secret in log output

**What:** Token is logged at INFO level.
**Why:** Secrets in logs leak to log aggregators.
**Fix:** Remove the token from the log statement.

```suggestion
    log.info("Token generated for user %s", user)
```
"""

MULTI_FINDINGS = """\
### [CRITICAL] [src/auth.py:12] Hardcoded secret

**What:** Secret is hardcoded.
**Why:** Exposed in source.
**Fix:** Use env var.

### [LOW] [src/utils.py:5] Unused import

**What:** os is imported but unused.
**Why:** Dead code.
**Fix:** Remove import.

### [MEDIUM] [src/auth.py:13] Log leak

**What:** Token in log.
**Why:** Leaks to aggregator.
**Fix:** Redact.
"""


# ---------------------------------------------------------------------------
# parse_findings
# ---------------------------------------------------------------------------

class TestParseFindings:
    def test_single_finding(self):
        findings = parse_findings(SAMPLE_FINDING, lens_name="security")
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "HIGH"
        assert f.file_path == "src/auth.py"
        assert f.line_num == 12
        assert f.title == "Secret in log output"
        assert "Token is logged" in f.body
        assert f.lens == "security"
        assert f.has_suggestion is False

    def test_finding_with_suggestion(self):
        findings = parse_findings(SAMPLE_FINDING_WITH_SUGGESTION)
        assert len(findings) == 1
        assert findings[0].has_suggestion is True
        assert "```suggestion" in findings[0].body

    def test_multiple_findings(self):
        findings = parse_findings(MULTI_FINDINGS, lens_name="review")
        assert len(findings) == 3
        assert findings[0].severity == "CRITICAL"
        assert findings[1].severity == "LOW"
        assert findings[2].severity == "MEDIUM"

    def test_empty_body(self):
        assert parse_findings("") == []
        assert parse_findings("No findings here.") == []

    def test_relaxed_fallback(self):
        relaxed_format = "## **HIGH** `src/auth.py:12` Secret leak\n\nDetails here."
        findings = parse_findings(relaxed_format)
        assert len(findings) == 1
        assert findings[0].file_path == "src/auth.py"
        assert findings[0].line_num == 12

    def test_lens_name_propagated(self):
        findings = parse_findings(SAMPLE_FINDING, lens_name="security")
        assert all(f.lens == "security" for f in findings)

    def test_leading_dot_slash_stripped(self):
        body = "### [HIGH] [./src/auth.py:12] Title\n\nBody."
        findings = parse_findings(body)
        assert findings[0].file_path == "src/auth.py"


# ---------------------------------------------------------------------------
# render_findings (roundtrip)
# ---------------------------------------------------------------------------

class TestRenderFindings:
    def test_roundtrip_preserves_structure(self):
        findings = parse_findings(MULTI_FINDINGS)
        rendered = render_findings(findings)
        reparsed = parse_findings(rendered)
        assert len(reparsed) == len(findings)
        for orig, re in zip(findings, reparsed):
            assert orig.severity == re.severity
            assert orig.file_path == re.file_path
            assert orig.line_num == re.line_num
            assert orig.title == re.title

    def test_suggestion_preserved(self):
        findings = parse_findings(SAMPLE_FINDING_WITH_SUGGESTION)
        rendered = render_findings(findings)
        assert "```suggestion" in rendered

    def test_empty_list(self):
        assert render_findings([]) == ""


# ---------------------------------------------------------------------------
# _build_diff_lines
# ---------------------------------------------------------------------------

class TestBuildDiffLines:
    def test_basic_diff(self):
        lines = _build_diff_lines(SAMPLE_DIFF)
        # Lines 10-17 should be present (context + additions)
        assert ("src/auth.py", 12) in lines  # first + line
        assert ("src/auth.py", 13) in lines  # second + line
        assert ("src/auth.py", 10) in lines  # context line

    def test_empty_diff(self):
        assert _build_diff_lines("") == set()


# ---------------------------------------------------------------------------
# verify_findings
# ---------------------------------------------------------------------------

class TestVerifyFindings:
    def test_line_in_diff_passes(self, tmp_path):
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "auth.py").write_text(
            "\n".join(f"line {i}" for i in range(1, 20))
        )
        findings = parse_findings(SAMPLE_FINDING)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert len(result) == 1
        assert result[0].in_diff is True
        assert result[0].verified is True

    def test_line_not_in_diff_downgraded(self, tmp_path):
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "auth.py").write_text(
            "\n".join(f"line {i}" for i in range(1, 100))
        )
        # Finding on line 50 — not in the diff
        body = "### [HIGH] [src/auth.py:50] Far from diff\n\nDetails."
        findings = parse_findings(body)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert result[0].in_diff is False
        assert "NOT found" in result[0].verification_log

    def test_tolerance_within_5_lines(self, tmp_path):
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "auth.py").write_text(
            "\n".join(f"line {i}" for i in range(1, 20))
        )
        # Line 15 is within ±5 of diff lines 10-14
        body = "### [HIGH] [src/auth.py:15] Near diff\n\nDetails."
        findings = parse_findings(body)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert result[0].in_diff is True

    def test_file_not_found(self, tmp_path):
        body = "### [HIGH] [nonexistent.py:5] Gone\n\nDetails."
        findings = parse_findings(body)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert result[0].verified is False
        assert "NOT found in checkout" in result[0].verification_log

    def test_line_beyond_eof(self, tmp_path):
        (tmp_path / "short.py").write_text("one\ntwo\nthree")
        body = "### [HIGH] [short.py:999] Beyond EOF\n\nDetails."
        findings = parse_findings(body)
        result = verify_findings(findings, "", tmp_path)
        assert result[0].verified is False
        assert "EOF" in result[0].verification_log

    def test_cross_file_claim_exists(self, tmp_path):
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "auth.py").write_text("\n".join(f"line {i}" for i in range(1, 20)))
        (tmp_path / "src" / "callers.py").write_text("import auth")
        body = "### [HIGH] [src/auth.py:12] Issue\n\nAlso called in `src/callers.py`."
        findings = parse_findings(body)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert "callers.py exists" in result[0].verification_log

    def test_cross_file_claim_missing(self, tmp_path):
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "auth.py").write_text("\n".join(f"line {i}" for i in range(1, 20)))
        body = "### [HIGH] [src/auth.py:12] Issue\n\nAlso called in `src/nowhere.py`."
        findings = parse_findings(body)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert "nowhere.py NOT found" in result[0].verification_log

    def test_suggestion_on_blank_line_flagged(self, tmp_path):
        """Suggestion targeting a blank line gets a 'misaligned' warning."""
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        # Line 13 is blank — suggestion targets it but it's empty
        lines = [f"line {i}" for i in range(1, 13)] + [""] + [f"line {i}" for i in range(14, 20)]
        (tmp_path / "src" / "auth.py").write_text("\n".join(lines))
        findings = parse_findings(SAMPLE_FINDING_WITH_SUGGESTION)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert "misaligned" in result[0].verification_log.lower()

    def test_suggestion_on_valid_line_passes(self, tmp_path):
        """Suggestion targeting a non-blank line gets 'target line exists'."""
        (tmp_path / "src" / "auth.py").parent.mkdir(parents=True, exist_ok=True)
        lines = [f"line {i}" for i in range(1, 20)]
        (tmp_path / "src" / "auth.py").write_text("\n".join(lines))
        findings = parse_findings(SAMPLE_FINDING_WITH_SUGGESTION)
        result = verify_findings(findings, SAMPLE_DIFF, tmp_path)
        assert "target line exists" in result[0].verification_log

    def test_empty_findings_noop(self, tmp_path):
        assert verify_findings([], SAMPLE_DIFF, tmp_path) == []


# ---------------------------------------------------------------------------
# score_findings
# ---------------------------------------------------------------------------

def _mock_haiku_success(scores: list[dict]) -> dict:
    """Create a mock subprocess result that mimics haiku's JSON output."""
    return {
        "result": json.dumps(scores),
        "session_id": "test-session",
        "num_turns": 1,
        "total_cost_usd": 0.001,
    }


class TestScoreFindings:
    def test_haiku_failure_passes_all_through(self, tmp_path):
        findings = parse_findings(MULTI_FINDINGS)
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run", side_effect=OSError("no claude")):
            result = score_findings(findings, tmp_path, config)
        assert len(result) == len(findings)

    def test_below_threshold_dropped(self, tmp_path):
        findings = parse_findings(MULTI_FINDINGS)
        scores = [
            {"index": 0, "score": 8, "reason": "good"},
            {"index": 1, "score": 3, "reason": "noise"},
            {"index": 2, "score": 7, "reason": "decent"},
        ]
        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": json.dumps(_mock_haiku_success(scores)),
        })()
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run", return_value=mock_result):
            result = score_findings(findings, tmp_path, config)
        assert len(result) == 2  # index 1 dropped (score 3 < threshold 6)
        assert all(f.confidence_score >= 6 for f in result)

    def test_timeout_passes_all_through(self, tmp_path):
        import subprocess
        findings = parse_findings(MULTI_FINDINGS)
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60)):
            result = score_findings(findings, tmp_path, config)
        assert len(result) == len(findings)

    def test_bad_json_passes_all_through(self, tmp_path):
        findings = parse_findings(MULTI_FINDINGS)
        mock_result = type("R", (), {
            "returncode": 0,
            "stdout": "not json at all",
        })()
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run", return_value=mock_result):
            result = score_findings(findings, tmp_path, config)
        assert len(result) == len(findings)


# ---------------------------------------------------------------------------
# _apply_total_cap
# ---------------------------------------------------------------------------

class TestApplyTotalCap:
    def _make_findings(self, count: int, severity: str = "MEDIUM",
                       score: float = 7.0) -> list[Finding]:
        return [
            Finding(severity=severity, file_path=f"f{i}.py", line_num=i,
                    title=f"Finding {i}", body="", confidence_score=score)
            for i in range(count)
        ]

    def test_under_cap_unchanged(self):
        findings = self._make_findings(3)
        assert len(_apply_total_cap(findings, total_cap=5, exempt_threshold=9)) == 3

    def test_over_cap_trimmed(self):
        findings = self._make_findings(10)
        result = _apply_total_cap(findings, total_cap=5, exempt_threshold=9)
        assert len(result) == 5

    def test_exempt_findings_bypass_cap(self):
        regular = self._make_findings(8, score=7.0)
        exempt = self._make_findings(2, severity="CRITICAL", score=9.5)
        all_findings = regular + exempt
        result = _apply_total_cap(all_findings, total_cap=5, exempt_threshold=9)
        # 2 exempt + 3 from cap = 5 total... but exempt bypass, so 2 + 3 = 5
        # Wait: remaining_cap = max(0, 5 - 2) = 3, so 3 regular + 2 exempt = 5
        assert len(result) == 5
        exempt_in_result = [f for f in result if f.confidence_score >= 9]
        assert len(exempt_in_result) == 2

    def test_zero_cap_means_unlimited(self):
        findings = self._make_findings(20)
        assert len(_apply_total_cap(findings, total_cap=0, exempt_threshold=9)) == 20

    def test_all_exempt_exceeds_cap(self):
        # All findings scored 10 — all bypass the cap
        findings = self._make_findings(10, score=10.0)
        result = _apply_total_cap(findings, total_cap=3, exempt_threshold=9)
        assert len(result) == 10  # all exempt

    def test_severity_ordering_preserved(self):
        findings = [
            Finding(severity="LOW", file_path="a.py", line_num=1,
                    title="low", body="", confidence_score=7.0),
            Finding(severity="CRITICAL", file_path="b.py", line_num=1,
                    title="crit", body="", confidence_score=7.0),
            Finding(severity="HIGH", file_path="c.py", line_num=1,
                    title="high", body="", confidence_score=7.0),
        ]
        result = _apply_total_cap(findings, total_cap=2, exempt_threshold=9)
        assert len(result) == 2
        # CRITICAL and HIGH should survive, LOW dropped
        severities = {f.severity for f in result}
        assert "CRITICAL" in severities
        assert "HIGH" in severities
