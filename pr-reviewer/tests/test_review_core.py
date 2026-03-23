"""Tests for review_core.py — shared review engine logic."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

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
        assert core.parse_command("@pr-reviewer") == ("standard", None)

    def test_deep(self):
        assert core.parse_command("@pr-reviewer deep") == ("deep", None)

    def test_stop(self):
        assert core.parse_command("@pr-reviewer stop") == ("stop", None)

    def test_random_text(self):
        assert core.parse_command("just a comment") is None

    def test_case_insensitive(self):
        assert core.parse_command("@PR-Reviewer Deep") == ("deep", None)

    def test_with_model_gemini(self):
        assert core.parse_command("@pr-reviewer with gemini") == ("standard", "gemini")

    def test_with_model_codex(self):
        assert core.parse_command("@pr-reviewer security with codex") == ("security", "codex")

    def test_with_model_claude(self):
        assert core.parse_command("@pr-reviewer deep with claude") == ("deep", "claude")

    def test_invalid_model(self):
        assert core.parse_command("@pr-reviewer with gpt4") == ("standard", None)


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


# ---------------------------------------------------------------------------
# analyze_diff_relevance
# ---------------------------------------------------------------------------

PYTHON_DIFF = """\
diff --git a/scripts/app.py b/scripts/app.py
--- a/scripts/app.py
+++ b/scripts/app.py
@@ -1,3 +1,5 @@
 import os
+def new_function():
+    pass
"""

CONFIG_DIFF = """\
diff --git a/config.yml b/config.yml
--- a/config.yml
+++ b/config.yml
@@ -1,3 +1,5 @@
 setting: true
+new_setting: false
"""

SECURITY_DIFF = """\
diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,3 +1,5 @@
+PASSWORD = "hardcoded_secret"
+api_token = os.environ["TOKEN"]
"""

NEW_FILE_DIFF = """\
diff --git a/new_service.py b/new_service.py
new file mode 100644
--- /dev/null
+++ b/new_service.py
@@ -0,0 +1,3 @@
+class NewService:
+    pass
"""


class TestAnalyzeDiffRelevance:
    def test_python_code_gets_simplification(self):
        result = core.analyze_diff_relevance(PYTHON_DIFF)
        assert "simplification" in result

    def test_config_gets_standards_and_drift(self):
        result = core.analyze_diff_relevance(CONFIG_DIFF)
        assert "standards" in result

    def test_security_patterns_get_security(self):
        result = core.analyze_diff_relevance(SECURITY_DIFF)
        assert "security" in result

    def test_new_files_get_architecture(self):
        result = core.analyze_diff_relevance(NEW_FILE_DIFF)
        assert "architecture" in result
        assert "drift" in result

    def test_empty_diff_returns_defaults(self):
        result = core.analyze_diff_relevance("")
        assert "simplification" in result
        assert "security" in result

    def test_mixed_diff_gets_multiple_lenses(self):
        mixed = PYTHON_DIFF + "\n" + SECURITY_DIFF
        result = core.analyze_diff_relevance(mixed)
        assert "simplification" in result
        assert "security" in result


# ---------------------------------------------------------------------------
# cap_by_severity
# ---------------------------------------------------------------------------

class TestCapBySeverity:
    def test_under_cap_unchanged(self):
        body = "### [HIGH] [f.py:1] Issue one\n\nDetails.\n\n### [LOW] [f.py:2] Issue two\n\nDetails."
        result = core.cap_by_severity(body, 5)
        assert "[HIGH]" in result
        assert "[LOW]" in result

    def test_over_cap_keeps_highest(self):
        body = (
            "### [LOW] [f.py:1] Low issue\n\nDetails.\n\n"
            "### [CRITICAL] [f.py:2] Critical issue\n\nDetails.\n\n"
            "### [MEDIUM] [f.py:3] Medium issue\n\nDetails."
        )
        result = core.cap_by_severity(body, 2)
        assert "[CRITICAL]" in result
        assert "[MEDIUM]" in result
        assert "[LOW]" not in result
        assert "Dropped 1" in result

    def test_unlimited_returns_unchanged(self):
        body = "### [HIGH] [f.py:1] Issue\n\nDetails."
        assert core.cap_by_severity(body, 0) == body

    def test_no_severity_markers(self):
        body = "Some review without markers."
        assert core.cap_by_severity(body, 3) == body


# ---------------------------------------------------------------------------
# preprocess_diff
# ---------------------------------------------------------------------------

DELETE_ONLY_DIFF = """\
diff --git a/old.py b/old.py
--- a/old.py
+++ b/old.py
@@ -1,5 +1,3 @@
 keep
-removed_line_1
-removed_line_2
 also_keep
"""

MIXED_DIFF = """\
diff --git a/old.py b/old.py
--- a/old.py
+++ b/old.py
@@ -1,5 +1,3 @@
 keep
-removed
 also_keep
diff --git a/new.py b/new.py
--- a/new.py
+++ b/new.py
@@ -1,3 +1,5 @@
 existing
+added_line
 end
"""


class TestPreprocessDiff:
    def test_strips_delete_only_files(self):
        result = core.preprocess_diff(DELETE_ONLY_DIFF)
        assert "old.py" not in result or result.strip() == ""

    def test_keeps_files_with_additions(self):
        result = core.preprocess_diff(MIXED_DIFF)
        assert "new.py" in result
        assert "added_line" in result

    def test_adds_language_annotation(self):
        result = core.preprocess_diff(MIXED_DIFF)
        assert "[Python]" in result

    def test_empty_diff_passthrough(self):
        assert core.preprocess_diff("") == ""

    def test_token_budget_truncation(self):
        # Create a diff larger than a tiny budget
        big_diff = MIXED_DIFF * 100
        result = core.preprocess_diff(big_diff, max_tokens=10)
        assert "Skipped" in result or len(result) < len(big_diff)


# ---------------------------------------------------------------------------
# build_review_prompt — structural invariants
# ---------------------------------------------------------------------------

class TestBuildReviewPromptStructure:
    def test_includes_preamble(self):
        (core.PROMPTS_DIR / "_preamble.md").write_text("PREAMBLE_MARKER")
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5)
        assert "PREAMBLE_MARKER" in result

    def test_includes_repomap_when_provided(self):
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5, repomap="file.py: def foo()")
        assert "Repository Structure" in result
        assert "def foo()" in result

    def test_includes_impact_when_provided(self):
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5, impact="auth.py: referenced by test_auth.py")
        assert "Impact Analysis" in result
        assert "referenced by" in result

    def test_includes_commit_messages(self):
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5, commit_messages="- fix auth bug")
        assert "Commit Messages" in result
        assert "fix auth bug" in result

    def test_no_extras_when_empty(self):
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5)
        assert "Repository Structure" not in result
        assert "Impact Analysis" not in result
        assert "Commit Messages" not in result


# ---------------------------------------------------------------------------
# run_lens_claude — command array verification
# ---------------------------------------------------------------------------

class TestRunLensClaude:
    @patch("subprocess.run")
    def test_includes_model_flag(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": ""}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        assert "sonnet" in cmd

    @patch("subprocess.run")
    def test_includes_allowed_tools(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": ""}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" in cmd
        tools_idx = cmd.index("--allowedTools") + 1
        tools = cmd[tools_idx]
        assert "Read" in tools
        assert "Grep" in tools
        assert "Bash(git:*)" in tools
        assert "Bash(sg:*)" in tools

    @patch("subprocess.run")
    def test_includes_max_turns(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": ""}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=15, model="opus")
        cmd = mock_run.call_args[0][0]
        assert "--max-turns" in cmd
        turns_idx = cmd.index("--max-turns") + 1
        assert cmd[turns_idx] == "15"

    @patch("subprocess.run")
    def test_includes_output_format_json(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": ""}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        cmd = mock_run.call_args[0][0]
        assert "--output-format" in cmd
        assert "json" in cmd


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    def test_claude_standard(self):
        config = {"models": {"claude": "sonnet", "claude_deep": "opus"}}
        assert core._resolve_model(config, "claude") == "sonnet"

    def test_claude_deep(self):
        config = {"models": {"claude": "sonnet", "claude_deep": "opus"}}
        assert core._resolve_model(config, "claude", depth="deep") == "opus"

    def test_gemini(self):
        config = {"models": {"gemini": "gemini-2.5-pro"}}
        assert core._resolve_model(config, "gemini") == "gemini-2.5-pro"

    def test_defaults_when_no_config(self):
        assert core._resolve_model({}, "claude") == "sonnet"

    def test_unknown_model_passes_through(self):
        assert core._resolve_model({}, "unknown_model") == "unknown_model"
