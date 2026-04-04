"""Scoring calibration: validate haiku/sonnet can distinguish good vs bad findings.

These tests call real LLM APIs — they won't run in CI.
Run manually: pytest -m calibration -v tests/test_scoring_calibration.py
"""

from __future__ import annotations

import logging

import pytest

from verification import Finding, score_findings

log = logging.getLogger(__name__)

# Five canonical bad findings — all should score below threshold (6)
BAD_FINDINGS = [
    Finding(
        severity="MEDIUM", file_path="src/auth.py", line_num=10,
        title="Consider adding error handling",
        body=(
            "This function could benefit from better error handling. "
            "Consider wrapping the call in a try/except block."
        ),
        lens="calibration",
    ),
    Finding(
        severity="HIGH", file_path="src/utils.py", line_num=999,
        title="Potential buffer overflow",
        body=(
            "Line 999 contains a potentially unsafe buffer operation that "
            "could overflow when given large input."
        ),
        lens="calibration",
    ),
    Finding(
        severity="LOW", file_path="src/models.py", line_num=15,
        title="Rename variable for clarity",
        body=(
            "The variable `x` on line 15 would be more readable as `user_count`. "
            "This improves maintainability."
        ),
        lens="calibration",
    ),
    Finding(
        severity="MEDIUM", file_path="src/api.py", line_num=42,
        title="Possible race condition",
        body=(
            "This might break if two requests hit this endpoint simultaneously. "
            "There could be a race condition, though I'm not sure about the exact mechanism."
        ),
        lens="calibration",
    ),
    Finding(
        severity="HIGH", file_path="src/config.py", line_num=8,
        title="Missing validation per ARCHITECTURE.md",
        body=(
            "As documented in ARCHITECTURE.md, all config values must be validated "
            "at load time. This field is not validated, violating the documented standard."
        ),
        lens="calibration",
    ),
]


def _setup_minimal_repo(tmp_path):
    """Create minimal repo where bad findings are obviously bad."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 30))
    )
    (tmp_path / "src" / "utils.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 51))  # 50 lines — line 999 is beyond EOF
    )
    (tmp_path / "src" / "models.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 30))
    )
    (tmp_path / "src" / "api.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 60))
    )
    (tmp_path / "src" / "config.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 20))
    )
    # Deliberately NO ARCHITECTURE.md — the hallucinated reference should fail


@pytest.mark.calibration
class TestScoringCalibration:
    """Validate scoring models can distinguish bad findings.

    These tests call real APIs. Run with: pytest -m calibration -v
    """

    def test_haiku_scores_bad_findings(self, tmp_path):
        """Haiku should score all bad findings below threshold 6."""
        _setup_minimal_repo(tmp_path)
        config = {
            "scoring_threshold": 6,
            "max_total_comments": 0,  # unlimited — don't interfere with scoring
            "scoring_exempt_threshold": 99,  # nothing exempt
        }

        result = score_findings(list(BAD_FINDINGS), tmp_path, config,
                                scoring_model="haiku")

        surviving = [(f.title, f.confidence_score) for f in result]
        for title, score in surviving:
            log.info("CALIBRATION haiku: '%s' scored %.1f", title, score)

        # At most 1 finding survives (allow one marginal case)
        assert len(result) <= 1, (
            f"Haiku scored {len(result)}/{len(BAD_FINDINGS)} bad findings above threshold. "
            f"Survivors: {surviving}"
        )

    def test_sonnet_scores_bad_findings(self, tmp_path):
        """Sonnet should score all bad findings below threshold 6."""
        _setup_minimal_repo(tmp_path)
        config = {
            "scoring_threshold": 6,
            "max_total_comments": 0,
            "scoring_exempt_threshold": 99,
        }

        result = score_findings(list(BAD_FINDINGS), tmp_path, config,
                                scoring_model="sonnet")

        surviving = [(f.title, f.confidence_score) for f in result]
        for title, score in surviving:
            log.info("CALIBRATION sonnet: '%s' scored %.1f", title, score)

        assert len(result) <= 1, (
            f"Sonnet scored {len(result)}/{len(BAD_FINDINGS)} bad findings above threshold. "
            f"Survivors: {surviving}"
        )

    def test_score_distribution_comparison(self, tmp_path):
        """Compare haiku vs sonnet score distributions on bad findings.

        This test always passes — it's a data collection exercise.
        Results are logged for human analysis.
        """
        _setup_minimal_repo(tmp_path)
        config = {
            "scoring_threshold": 0,  # keep ALL findings (don't filter)
            "max_total_comments": 0,
            "scoring_exempt_threshold": 99,
        }

        haiku_result = score_findings(list(BAD_FINDINGS), tmp_path, config,
                                      scoring_model="haiku")
        sonnet_result = score_findings(list(BAD_FINDINGS), tmp_path, config,
                                       scoring_model="sonnet")

        log.info("=" * 60)
        log.info("SCORING CALIBRATION: haiku vs sonnet on bad findings")
        log.info("%-40s  %6s  %6s", "Finding", "Haiku", "Sonnet")
        log.info("-" * 60)

        haiku_scores = {f.title: f.confidence_score for f in haiku_result}
        sonnet_scores = {f.title: f.confidence_score for f in sonnet_result}

        for bf in BAD_FINDINGS:
            h = haiku_scores.get(bf.title, -1)
            s = sonnet_scores.get(bf.title, -1)
            log.info("%-40s  %6.1f  %6.1f", bf.title[:40], h, s)

        log.info("=" * 60)
