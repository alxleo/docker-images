"""Scoring calibration tests — verify that scoring pipeline handles
good vs bad findings correctly via mocked haiku responses."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from verification import Finding, score_findings


def _mock_haiku_response(scores: list[dict]) -> subprocess.CompletedProcess:
    """Create a mock subprocess result mimicking haiku's JSON output."""
    return subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({
            "result": json.dumps(scores),
            "session_id": "calibration-test",
            "num_turns": 1,
            "total_cost_usd": 0.001,
        }),
    )


# ---------------------------------------------------------------------------
# Synthetic findings: bad (vague, speculative, wrong)
# ---------------------------------------------------------------------------

BAD_FINDINGS = [
    Finding(severity="MEDIUM", file_path="src/app.py", line_num=1,
            title="Consider adding error handling",
            body="This function could potentially fail. Consider adding try/except.",
            lens="simplification"),
    Finding(severity="HIGH", file_path="nonexistent.py", line_num=99,
            title="Possible security issue",
            body="This might be a security risk. It's hard to tell without more context.",
            lens="security", verified=False),
    Finding(severity="LOW", file_path="src/utils.py", line_num=5,
            title="Style suggestion",
            body="You could rename this variable for clarity.",
            lens="simplification"),
]

# ---------------------------------------------------------------------------
# Synthetic findings: good (concrete, evidenced)
# ---------------------------------------------------------------------------

GOOD_FINDINGS = [
    Finding(severity="CRITICAL", file_path="src/auth.py", line_num=12,
            title="Secret logged at INFO level",
            body="**What:** `generate_token()` return value logged via `log.info('Token: %s', token)`.\n"
                 "**Why:** Secrets in structured logs leak to aggregators.\n"
                 "**Fix:** Remove token from log call.\n```suggestion\n    log.info('Token generated')\n```",
            lens="security", has_suggestion=True),
    Finding(severity="HIGH", file_path="src/db.py", line_num=45,
            title="SQL injection via string formatting",
            body="**What:** `cursor.execute(f'SELECT * FROM users WHERE id={user_id}')` uses f-string.\n"
                 "**Why:** Direct string interpolation in SQL enables injection.\n"
                 "**Fix:** Use parameterized query.\n```suggestion\n    cursor.execute('SELECT * FROM users WHERE id=?', (user_id,))\n```",
            lens="security", has_suggestion=True),
]


class TestScoringCalibration:
    """Verify that the scoring pipeline assigns appropriate scores."""

    def test_bad_findings_score_low(self, tmp_path):
        """Vague/speculative findings should score below threshold."""
        scores = [
            {"index": 0, "score": 3, "reason": "vague, no concrete fix"},
            {"index": 1, "score": 2, "reason": "speculative, file doesn't exist"},
            {"index": 2, "score": 1, "reason": "style only, not actionable"},
        ]
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run",
                   return_value=_mock_haiku_response(scores)):
            result = score_findings(BAD_FINDINGS.copy(), tmp_path, config)
        # All should be dropped (below threshold 6)
        assert len(result) == 0

    def test_good_findings_score_high(self, tmp_path):
        """Concrete, evidenced findings should score above threshold."""
        scores = [
            {"index": 0, "score": 9, "reason": "concrete secret leak with suggestion"},
            {"index": 1, "score": 8, "reason": "proven SQL injection with fix"},
        ]
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run",
                   return_value=_mock_haiku_response(scores)):
            result = score_findings(GOOD_FINDINGS.copy(), tmp_path, config)
        assert len(result) == 2
        assert all(f.confidence_score >= 6 for f in result)

    def test_mixed_findings_filtered_correctly(self, tmp_path):
        """Mix of good and bad findings: only good ones survive."""
        all_findings = BAD_FINDINGS.copy() + GOOD_FINDINGS.copy()
        scores = [
            {"index": 0, "score": 3, "reason": "vague"},
            {"index": 1, "score": 2, "reason": "speculative"},
            {"index": 2, "score": 1, "reason": "style"},
            {"index": 3, "score": 9, "reason": "concrete secret leak"},
            {"index": 4, "score": 8, "reason": "proven injection"},
        ]
        config = {"scoring_threshold": 6, "max_total_comments": 0}
        with patch("verification.subprocess.run",
                   return_value=_mock_haiku_response(scores)):
            result = score_findings(all_findings, tmp_path, config)
        assert len(result) == 2
        assert any("Secret" in f.title for f in result)
        assert any("SQL" in f.title for f in result)

    def test_scoring_model_configurable(self, tmp_path):
        """scoring_model config should be passed to the CLI command."""
        scores = [{"index": 0, "score": 7, "reason": "ok"}]
        config = {"scoring_model": "sonnet", "scoring_threshold": 6, "max_total_comments": 0}
        findings = [GOOD_FINDINGS[0]]
        with patch("verification.subprocess.run",
                   return_value=_mock_haiku_response(scores)) as mock_run:
            score_findings(findings, tmp_path, config)
        cmd = mock_run.call_args[0][0]
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "sonnet"

    def test_exempt_findings_bypass_cap(self, tmp_path):
        """High-confidence findings should bypass the total cap."""
        all_findings = BAD_FINDINGS.copy() + GOOD_FINDINGS.copy()
        scores = [
            {"index": 0, "score": 7, "reason": "decent"},
            {"index": 1, "score": 7, "reason": "decent"},
            {"index": 2, "score": 7, "reason": "decent"},
            {"index": 3, "score": 10, "reason": "critical"},  # exempt
            {"index": 4, "score": 9, "reason": "proven"},      # exempt
        ]
        config = {
            "scoring_threshold": 6,
            "max_total_comments": 2,
            "scoring_exempt_threshold": 9,
        }
        with patch("verification.subprocess.run",
                   return_value=_mock_haiku_response(scores)):
            result = score_findings(all_findings, tmp_path, config)
        # 2 exempt (scores 10, 9) + 0 from cap (cap=2, 2 exempt fill it)
        exempt = [f for f in result if f.confidence_score >= 9]
        assert len(exempt) == 2
