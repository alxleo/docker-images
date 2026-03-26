"""Tests for review_core.py — shared review engine logic."""

import json
from unittest.mock import patch, MagicMock

import pytest

import config as cfg
import review_core as core
from models import ReviewResult


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Patch paths in all modules that reference them."""
    import models as models_mod
    for mod in (cfg, core, models_mod):
        monkeypatch.setattr(mod, "STATE_DIR", tmp_path / "state")
    for mod in (cfg, core):
        monkeypatch.setattr(mod, "REPOS_DIR", tmp_path / "repos")
        monkeypatch.setattr(mod, "PROMPTS_DIR", tmp_path / "prompts")
    # Modules that import PROMPTS_DIR from config at import time
    import prompts as prompts_mod
    import context as context_mod
    monkeypatch.setattr(prompts_mod, "PROMPTS_DIR", tmp_path / "prompts")
    monkeypatch.setattr(context_mod, "PROMPTS_DIR", tmp_path / "prompts")
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
        names = [lens["name"] for lens in result]
        assert names == ["simplification", "security"]

    def test_auto_default_max_comments(self, config):
        result = core.enabled_lenses(config, "auto")
        assert all(lens["max_comments"] == 5 for lens in result)

    def test_auto_respects_override(self, config):
        config["auto_overrides"] = {"max_comments": 3}
        result = core.enabled_lenses(config, "auto")
        assert all(lens["max_comments"] == 3 for lens in result)

    def test_auto_defaults_without_config(self):
        config = {"lenses": {}}
        result = core.enabled_lenses(config, "auto")
        names = [lens["name"] for lens in result]
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

    def test_includes_cross_file_context(self):
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5,
                                          cross_file_context="callers: app.py:42 my_func()")
        assert "Cross-File Context" in result
        assert "my_func" in result

    def test_no_extras_when_empty(self):
        (core.PROMPTS_DIR / "security.md").write_text("Security lens.")
        result = core.build_review_prompt("security", "diff", 5)
        assert "Repository Structure" not in result
        assert "Impact Analysis" not in result
        assert "Commit Messages" not in result
        assert "Cross-File Context" not in result


# ---------------------------------------------------------------------------
# run_lens_claude — command array verification
# ---------------------------------------------------------------------------

class TestRunLensClaude:
    @patch("subprocess.run")
    def test_includes_model_flag(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": "", "session_id": "test-session", "num_turns": 1, "total_cost_usd": 0.01, "duration_ms": 1000, "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0}, "stop_reason": "end_turn"}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        assert "sonnet" in cmd

    @patch("subprocess.run")
    def test_includes_allowed_tools(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": "", "session_id": "test-session", "num_turns": 1, "total_cost_usd": 0.01, "duration_ms": 1000, "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0}, "stop_reason": "end_turn"}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" in cmd
        tools_idx = cmd.index("--allowedTools") + 1
        tools = cmd[tools_idx]
        assert "Read" in tools
        assert "Grep" in tools
        assert "Bash(git log:*)" in tools
        assert "Bash(git blame:*)" in tools
        assert "Bash(sg:*)" in tools
        assert "Agent" in tools
        # MUST NOT have unrestricted git access (no commit/push/checkout)
        assert "Bash(git:*)" not in tools
        assert "Edit" not in tools
        assert "Write" not in tools

    @patch("subprocess.run")
    def test_includes_max_turns(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": "", "session_id": "test-session", "num_turns": 1, "total_cost_usd": 0.01, "duration_ms": 1000, "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0}, "stop_reason": "end_turn"}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=15, model="opus")
        cmd = mock_run.call_args[0][0]
        assert "--max-turns" in cmd
        turns_idx = cmd.index("--max-turns") + 1
        assert cmd[turns_idx] == "15"

    @patch("subprocess.run")
    def test_includes_output_format_json(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": "", "session_id": "test-session", "num_turns": 1, "total_cost_usd": 0.01, "duration_ms": 1000, "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0}, "stop_reason": "end_turn"}', stderr=""
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        cmd = mock_run.call_args[0][0]
        assert "--output-format" in cmd
        assert "json" in cmd

    @patch("subprocess.run")
    def test_config_model_reaches_cli(self, mock_run, config, tmp_path):
        """Model from config.models should reach the subprocess command."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"result": "", "session_id": "test-session", "num_turns": 1, "total_cost_usd": 0.01, "duration_ms": 1000, "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0}, "stop_reason": "end_turn"}', stderr=""
        )
        (core.PROMPTS_DIR / "simplification.md").write_text("prompt")
        config["models"] = {"claude": "opus", "claude_deep": "opus"}
        lens = {"name": "simplification", "max_comments": 5}
        core.run_lens(lens, "diff", tmp_path, config, depth="standard")
        cmd = mock_run.call_args[0][0]
        model_idx = cmd.index("--model") + 1
        assert cmd[model_idx] == "opus"


    @patch("subprocess.run")
    def test_returns_review_result_with_metadata(self, mock_run, tmp_path):
        """run_lens_claude should return ReviewResult with all fields populated."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "finding text",
                "session_id": "abc-123",
                "num_turns": 7,
                "total_cost_usd": 0.42,
                "duration_ms": 180000,
                "usage": {"input_tokens": 12000, "output_tokens": 3000, "cache_read_input_tokens": 5000},
                "stop_reason": "end_turn",
            }),
            stderr="",
        )
        result = core.run_lens_claude("prompt", tmp_path, max_turns=10, model="sonnet")
        assert result.text == "finding text"
        assert result.session_id == "abc-123"
        assert result.num_turns == 7
        assert result.max_turns == 10
        assert result.cost_usd == 0.42
        assert result.duration_ms == 180000
        assert result.input_tokens == 17000  # 12000 + 5000 cache_read
        assert result.output_tokens == 3000
        assert result.stop_reason == "end_turn"

    @patch("subprocess.run")
    def test_saves_session_metadata_to_disk(self, mock_run, tmp_path):
        """Full Claude JSON should be persisted to state/sessions/."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "text",
                "session_id": "persist-test-123",
                "num_turns": 1,
                "total_cost_usd": 0.01,
                "duration_ms": 1000,
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "stop_reason": "end_turn",
            }),
            stderr="",
        )
        core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        session_file = tmp_path / "state" / "sessions" / "persist-test-123.json"
        assert session_file.exists()
        saved = json.loads(session_file.read_text())
        assert saved["session_id"] == "persist-test-123"
        assert saved["total_cost_usd"] == 0.01

    @patch("subprocess.run")
    def test_failure_returns_empty_review_result(self, mock_run, tmp_path):
        """Non-zero exit code should return empty ReviewResult."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = core.run_lens_claude("prompt", tmp_path, max_turns=5, model="sonnet")
        assert not result
        assert result.text == ""
        assert result.max_turns == 5

    def test_review_result_bool(self):
        """ReviewResult should be truthy only when text is non-empty."""
        assert ReviewResult(text="finding")
        assert not ReviewResult(text="")
        assert not ReviewResult(text="   ")


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


# ---------------------------------------------------------------------------
# generate_repomap
# ---------------------------------------------------------------------------

class TestGenerateRepomap:
    def test_extracts_python_definitions(self, tmp_path):
        py_file = tmp_path / "app.py"
        py_file.write_text("class MyApp:\n    pass\n\ndef main():\n    pass\n")
        result = core.generate_repomap(tmp_path)
        assert "class MyApp:" in result
        assert "def main():" in result
        assert "app.py" in result

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".git" / "objects"
        hidden.mkdir(parents=True)
        (hidden / "pack.py").write_text("def internal(): pass")
        result = core.generate_repomap(tmp_path)
        assert "internal" not in result

    def test_respects_max_chars(self, tmp_path):
        for i in range(20):
            (tmp_path / f"mod{i}.py").write_text(f"def func_{i}(): pass\n" * 10)
        result = core.generate_repomap(tmp_path, max_chars=200)
        assert len(result) <= 300  # some slack for truncation message

    def test_empty_repo_returns_empty(self, tmp_path):
        assert core.generate_repomap(tmp_path) == ""

    def test_non_code_files_skipped(self, tmp_path):
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "config.yml").write_text("key: value")
        assert core.generate_repomap(tmp_path) == ""

    def test_diff_triggers_pagerank_path(self, tmp_path):
        """When diff is provided, files referenced by diff should rank higher."""
        # Create a small multi-file repo with cross-references
        (tmp_path / "models.py").write_text("class User:\n    pass\n\nclass Order:\n    pass\n")
        (tmp_path / "views.py").write_text("from models import User\ndef get_user():\n    return User()\n")
        (tmp_path / "tests.py").write_text("from views import get_user\ndef test_user():\n    get_user()\n")
        (tmp_path / "unrelated.py").write_text("def standalone():\n    pass\n")

        diff = "--- a/views.py\n+++ b/views.py\n@@ -1,3 +1,3 @@\n+from models import User\n"
        result = core.generate_repomap(tmp_path, diff=diff)
        # views.py is in the diff, models.py is referenced by views.py — both should appear
        assert "views.py" in result
        assert "models.py" in result

    def test_no_diff_uses_simple_fallback(self, tmp_path):
        """Empty diff should produce alphabetical listing (backwards compat)."""
        (tmp_path / "alpha.py").write_text("def a_func(): pass\n")
        (tmp_path / "beta.py").write_text("def b_func(): pass\n")
        result = core.generate_repomap(tmp_path)
        assert "alpha.py" in result
        assert "beta.py" in result

    def test_max_chars_with_diff(self, tmp_path):
        for i in range(20):
            (tmp_path / f"mod{i}.py").write_text(f"def func_{i}(): pass\n" * 10)
        diff = "--- a/mod0.py\n+++ b/mod0.py\n@@ -1 +1 @@\n+def func_0(): pass\n"
        result = core.generate_repomap(tmp_path, diff=diff, max_chars=200)
        assert len(result) <= 300  # slack for truncation marker


class TestPageRank:
    def test_personalization_biases_ranking(self):
        """Diff files should rank higher than unrelated files."""
        from context import pagerank
        edges = {
            "app.py": {"utils.py": 1.4, "models.py": 1.0},
            "utils.py": {"models.py": 1.0},
            "models.py": {"models.py": 0.1},
            "unrelated.py": {"unrelated.py": 0.1},
        }
        ranks = pagerank(edges, {"app.py": 1.0})
        # app.py is personalized — models.py is the hub it points to
        assert ranks["models.py"] > ranks["unrelated.py"]
        assert ranks["app.py"] > ranks["unrelated.py"]

    def test_empty_graph(self):
        from context import pagerank
        assert pagerank({}, {}) == {}

    def test_single_node(self):
        from context import pagerank
        edges = {"a.py": {"a.py": 0.1}}
        ranks = pagerank(edges, {"a.py": 1.0})
        assert "a.py" in ranks
        assert ranks["a.py"] > 0


class TestExtractFileTags:
    def test_extracts_defs_and_refs(self, tmp_path):
        from context import extract_file_tags, _get_parser
        py_file = tmp_path / "example.py"
        py_file.write_text("import os\n\ndef hello():\n    os.path.join('a', 'b')\n\nclass Foo:\n    def method(self):\n        hello()\n")
        pair = _get_parser("python")
        assert pair is not None
        lang, parser = pair
        tags = extract_file_tags(py_file, lang, parser)
        assert tags is not None
        assert "hello" in tags.defs
        assert "Foo" in tags.defs
        assert "method" in tags.defs
        assert "os" in tags.refs
        # hello is a def, not a ref in this file
        assert "hello" not in tags.refs

    def test_nested_class_methods(self, tmp_path):
        from context import extract_file_tags, _get_parser
        py_file = tmp_path / "nested.py"
        py_file.write_text("class Outer:\n    class Inner:\n        def deep_method(self):\n            pass\n")
        pair = _get_parser("python")
        lang, parser = pair
        tags = extract_file_tags(py_file, lang, parser)
        assert "Outer" in tags.defs
        assert "deep_method" in tags.defs


# ---------------------------------------------------------------------------
# plan_searches
# ---------------------------------------------------------------------------

class TestPlanSearches:
    @patch("subprocess.run")
    def test_disabled_returns_empty(self, mock_run, tmp_path):
        config = {"planned_searches": False}
        assert core.plan_searches("diff", tmp_path, config) == ""
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_planner_generates_and_executes_queries(self, mock_run, tmp_path):
        """If planner returns queries, rg should be called for each."""
        (core.PROMPTS_DIR / "_planner.md").write_text("planner prompt")
        # First call: claude planner returns JSON queries
        planner_output = json.dumps({
            "result": '[{"pattern": "my_function", "category": "callers", "rationale": "find callers"}]'
        })
        # Second call: rg finds matches
        rg_output = "scripts/app.py:42:    my_function()"

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=planner_output, stderr=""),  # claude
            MagicMock(returncode=0, stdout=rg_output, stderr=""),       # rg
        ]
        result = core.plan_searches("diff content", tmp_path, {})
        assert "my_function" in result
        assert "callers" in result
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_planner_failure_returns_empty(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = core.plan_searches("diff", tmp_path, {})
        assert result == ""


# ---------------------------------------------------------------------------
# shuffle_diff
# ---------------------------------------------------------------------------

class TestShuffleDiff:
    def test_single_file_unchanged(self):
        diff = "diff --git a/f.py b/f.py\n+added\n"
        assert core.shuffle_diff(diff) == diff

    def test_multi_file_contains_all_files(self):
        diff = (
            "diff --git a/a.py b/a.py\n+a_content\n"
            "diff --git a/b.py b/b.py\n+b_content\n"
            "diff --git a/c.py b/c.py\n+c_content\n"
        )
        result = core.shuffle_diff(diff)
        assert "a_content" in result
        assert "b_content" in result
        assert "c_content" in result

    def test_empty_diff(self):
        assert core.shuffle_diff("") == ""

    def test_preprocessed_format(self):
        """Preprocessed diffs use ## headers instead of diff --git."""
        diff = (
            "## a.py [Python]\ndiff --git a/a.py b/a.py\n+a_content\n"
            "## b.py [Python]\ndiff --git a/b.py b/b.py\n+b_content\n"
        )
        result = core.shuffle_diff(diff)
        assert "a_content" in result
        assert "b_content" in result
        assert "## a.py" in result
        assert "## b.py" in result


# ---------------------------------------------------------------------------
# run_review_orchestrated
# ---------------------------------------------------------------------------

class TestRunReviewOrchestrated:
    @patch("orchestrator.run_lens_claude", return_value=ReviewResult(text="### [HIGH] [f.py:1] Finding\n\nDetail."))
    def test_claude_lenses_use_single_session(self, mock_claude, config, tmp_path):
        """Multiple Claude lenses should result in ONE run_lens_claude call."""
        (core.PROMPTS_DIR / "_preamble.md").write_text("preamble")
        lenses = [
            {"name": "simplification", "max_comments": 5},
            {"name": "security", "max_comments": 5},
        ]
        config["default_model"] = "claude"
        results = core.run_review_orchestrated(lenses, "diff", tmp_path, config)
        # One call, not two
        assert mock_claude.call_count == 1
        assert len(results) >= 1

    @patch("orchestrator.run_lens_claude", return_value=ReviewResult(text=""))
    @patch("routing.run_lens_gemini", return_value="gemini finding")
    def test_non_claude_lenses_use_individual_calls(self, mock_gemini, mock_claude, config, tmp_path):
        """Gemini lenses should bypass orchestrator and use run_lens individually."""
        (core.PROMPTS_DIR / "_preamble.md").write_text("preamble")
        (core.PROMPTS_DIR / "security.md").write_text("security lens")
        lenses = [
            {"name": "simplification", "max_comments": 5},
            {"name": "security", "max_comments": 5},
        ]
        config["default_model"] = "claude"
        config["lenses"]["security"]["model"] = "gemini"
        core.run_review_orchestrated(lenses, "diff", tmp_path, config)
        # Claude called once (for simplification), Gemini called once (for security)
        assert mock_claude.call_count == 1
        assert mock_gemini.call_count == 1

    @patch("orchestrator.run_lens_claude", return_value=ReviewResult(text="finding"))
    def test_single_lens_returns_lens_name(self, mock_claude, config, tmp_path):
        """Single Claude lens should return the lens name, not 'review'."""
        (core.PROMPTS_DIR / "_preamble.md").write_text("preamble")
        lenses = [{"name": "simplification", "max_comments": 5}]  # simplification uses default=claude
        config["default_model"] = "claude"
        results = core.run_review_orchestrated(lenses, "diff", tmp_path, config)
        assert results[0][0] == "simplification"  # not "review"

    @patch("orchestrator.run_lens_claude", return_value=ReviewResult(text="finding"))
    def test_multi_lens_returns_review_label(self, mock_claude, config, tmp_path):
        """Multiple Claude lenses should return 'review' label."""
        (core.PROMPTS_DIR / "_preamble.md").write_text("preamble")
        lenses = [
            {"name": "simplification", "max_comments": 5},
            {"name": "standards", "max_comments": 5},  # standards uses default=claude
        ]
        config["default_model"] = "claude"
        results = core.run_review_orchestrated(lenses, "diff", tmp_path, config)
        assert results[0][0] == "review"

    @patch("orchestrator.run_lens_claude", return_value=ReviewResult(text=""))
    def test_empty_result_not_returned(self, mock_claude, config, tmp_path):
        (core.PROMPTS_DIR / "_preamble.md").write_text("preamble")
        lenses = [{"name": "simplification", "max_comments": 5}]
        config["default_model"] = "claude"
        results = core.run_review_orchestrated(lenses, "diff", tmp_path, config)
        assert results == []

    @patch("orchestrator.run_lens_claude", return_value=ReviewResult(text="finding"))
    def test_orchestrator_prompt_includes_agent_instructions(self, mock_claude, config, tmp_path):
        """The orchestrator prompt should tell Claude which agents to spawn."""
        (core.PROMPTS_DIR / "_preamble.md").write_text("preamble")
        # Use lenses that all default to claude (simplification + standards)
        lenses = [
            {"name": "simplification", "max_comments": 5},
            {"name": "standards", "max_comments": 5},
        ]
        config["default_model"] = "claude"
        core.run_review_orchestrated(lenses, "diff", tmp_path, config)
        prompt = mock_claude.call_args.kwargs.get("prompt") or mock_claude.call_args[0][0]
        assert "pr-reviewer-lenses:simplification-lens" in prompt
        assert "pr-reviewer-lenses:standards-lens" in prompt
