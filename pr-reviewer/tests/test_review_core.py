"""Tests for review_core.py — shared review engine logic."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import review_core as core


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(core, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(core, "PROMPTS_DIR", tmp_path / "prompts")
    (tmp_path / "state").mkdir()
    (tmp_path / "repos").mkdir()
    (tmp_path / "prompts").mkdir()


@pytest.fixture()
def config():
    return {
        "lenses": {
            "simplification": {"max_comments": 5},
            "security": {"max_comments": 5, "model": "gemini"},
            "standards": {"max_comments": 5},
            "drift": {"max_comments": 5, "enabled": False},
        },
        "auto_lenses": ["simplification", "security"],
    }


# ---------------------------------------------------------------------------
# enabled_lenses — auto depth
# ---------------------------------------------------------------------------

class TestAutoLenses:
    def test_auto_uses_configured_lenses(self, config):
        result = core.enabled_lenses(config, "auto")
        names = [l["name"] for l in result]
        assert names == ["simplification", "security"]

    def test_auto_default_max_comments(self, config):
        result = core.enabled_lenses(config, "auto")
        assert all(l["max_comments"] == 5 for l in result)

    def test_auto_respects_override(self, config):
        config["auto_overrides"] = {"max_comments": 3}
        result = core.enabled_lenses(config, "auto")
        assert all(l["max_comments"] == 3 for l in result)

    def test_auto_defaults_without_config(self):
        config = {"lenses": {}}
        result = core.enabled_lenses(config, "auto")
        names = [l["name"] for l in result]
        assert names == ["simplification", "security"]

    def test_auto_custom_lens_list(self, config):
        config["auto_lenses"] = ["standards"]
        result = core.enabled_lenses(config, "auto")
        assert len(result) == 1
        assert result[0]["name"] == "standards"


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_bare_review(self):
        assert core.parse_command("@pr-reviewer") == "standard"

    def test_deep(self):
        assert core.parse_command("@pr-reviewer deep") == "deep"

    def test_stop(self):
        assert core.parse_command("@pr-reviewer stop") == "stop"

    def test_random_text(self):
        assert core.parse_command("just a comment") is None

    def test_case_insensitive(self):
        assert core.parse_command("@PR-Reviewer Deep") == "deep"


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

class TestState:
    def test_load_empty(self):
        assert core.load_state("o/r", 1) == {}

    def test_roundtrip(self):
        data = {"last_head_sha": "abc", "last_reviewed_at": 123.4}
        core.save_state("o/r", 42, data)
        assert core.load_state("o/r", 42) == data

    def test_slash_in_filename(self):
        core.save_state("owner/repo", 1, {"key": "val"})
        expected = core.STATE_DIR / "owner_repo_pr1.json"
        assert expected.exists()


# ---------------------------------------------------------------------------
# build_review_prompt
# ---------------------------------------------------------------------------

class TestBuildReviewPrompt:
    def test_valid_prompt(self):
        (core.PROMPTS_DIR / "security.md").write_text("You are a security reviewer.")
        result = core.build_review_prompt("security", "diff content", 5)
        assert "You are a security reviewer." in result
        assert "```diff\ndiff content\n```" in result
        assert "MAX COMMENTS: 5" in result

    def test_missing_prompt(self):
        assert core.build_review_prompt("nonexistent", "diff", 5) == ""

    def test_unlimited(self):
        (core.PROMPTS_DIR / "deep.md").write_text("Deep review.")
        result = core.build_review_prompt("deep", "diff", 0)
        assert "MAX COMMENTS" not in result


# ---------------------------------------------------------------------------
# parse_inline_comments
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -10,6 +10,8 @@
   existing line
   another line
+  new_code = True
+  more_new = False

 - name: task
"""


class TestParseInlineComments:
    def test_basic(self):
        body = "### [src/app.py:12] Over-complex\n\nSimplify this."
        comments = core.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 1
        assert comments[0]["path"] == "src/app.py"
        assert comments[0]["line"] == 12

    def test_not_in_diff(self):
        body = "### [src/app.py:99] Not here\n\nBody."
        assert core.parse_inline_comments(body, SAMPLE_DIFF) == []

    def test_no_findings(self):
        assert core.parse_inline_comments("looks good!", SAMPLE_DIFF) == []

    def test_severity_prefix(self):
        body = "### [HIGH] [src/app.py:12] Issue\n\nDetails."
        comments = core.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 1
