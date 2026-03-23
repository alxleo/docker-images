"""Unit tests for gh-watcher.py — pure logic, no Docker/GitHub/AI CLIs needed."""

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import review_core as core
import gh_watcher as w


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Redirect all module-level paths to tmp dirs.

    Must patch both review_core (where functions read the values) and
    gh_watcher (for backwards-compat re-exports).
    """
    for mod in (core, w):
        monkeypatch.setattr(mod, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(mod, "REPOS_DIR", tmp_path / "repos")
        monkeypatch.setattr(mod, "PROMPTS_DIR", tmp_path / "prompts")
    (tmp_path / "state").mkdir()
    (tmp_path / "repos").mkdir()
    (tmp_path / "prompts").mkdir()


@pytest.fixture()
def config():
    """Minimal valid config."""
    return {
        "repos": ["owner/repo-a"],
        "owner_filter": "owner",
        "default_depth": "standard",
        "polling_interval": 60,
        "skip_drafts": True,
        "lenses": {
            "simplification": {"max_comments": 5},
            "standards": {"max_comments": 5},
            "security": {"max_comments": 5, "model": "gemini"},
            "drift": {"max_comments": 5, "enabled": False},
        },
    }


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_bare_review(self):
        assert w.parse_command("@pr-reviewer") == ("standard", None)

    def test_deep(self):
        assert w.parse_command("@pr-reviewer deep") == ("deep", None)

    def test_security(self):
        assert w.parse_command("@pr-reviewer security") == ("security", None)

    def test_standards(self):
        assert w.parse_command("@pr-reviewer standards") == ("standards", None)

    def test_drift(self):
        assert w.parse_command("@pr-reviewer drift") == ("drift", None)

    def test_simplification(self):
        assert w.parse_command("@pr-reviewer simplification") == ("simplification", None)

    def test_quick(self):
        assert w.parse_command("@pr-reviewer quick") == ("quick", None)

    def test_stop(self):
        assert w.parse_command("@pr-reviewer stop") == ("stop", None)

    def test_random_text_returns_none(self):
        assert w.parse_command("just a regular comment") is None

    def test_whitespace_stripped(self):
        assert w.parse_command("  @pr-reviewer  ") == ("standard", None)

    def test_trailing_text_still_matches(self):
        assert w.parse_command("@pr-reviewer deep please look at auth") == ("deep", None)

    def test_case_insensitive(self):
        assert w.parse_command("@PR-Reviewer Deep") == ("deep", None)

    def test_empty_string(self):
        assert w.parse_command("") is None

    def test_partial_prefix_no_match(self):
        assert w.parse_command("@rev") is None

    def test_with_model_override(self):
        assert w.parse_command("@pr-reviewer with gemini") == ("standard", "gemini")

    def test_depth_with_model(self):
        assert w.parse_command("@pr-reviewer deep with codex") == ("deep", "codex")

    def test_invalid_model_ignored(self):
        assert w.parse_command("@pr-reviewer with banana") == ("standard", None)



# ---------------------------------------------------------------------------
# enabled_lenses
# ---------------------------------------------------------------------------

class TestEnabledLenses:
    def test_single_lens_security(self, config):
        result = w.enabled_lenses(config, "security")
        assert len(result) == 1
        assert result[0]["name"] == "security"
        assert result[0]["max_comments"] == 5

    def test_single_lens_simplification(self, config):
        result = w.enabled_lenses(config, "simplification")
        assert len(result) == 1
        assert result[0]["name"] == "simplification"

    def test_single_lens_unknown_uses_defaults(self, config):
        result = w.enabled_lenses(config, "standards")
        assert result[0]["max_comments"] == 5

    def test_quick_defaults(self, config):
        result = w.enabled_lenses(config, "quick")
        assert len(result) == 1
        assert result[0]["name"] == "simplification"
        assert result[0]["max_comments"] == 3

    def test_quick_with_overrides(self, config):
        config["quick_overrides"] = {"lenses": ["security", "standards"], "max_comments": 2}
        result = w.enabled_lenses(config, "quick")
        assert len(result) == 2
        assert all(l["max_comments"] == 2 for l in result)

    def test_standard_skips_disabled(self, config):
        result = w.enabled_lenses(config, "standard")
        names = [l["name"] for l in result]
        assert "drift" not in names
        assert "simplification" in names
        assert "standards" in names

    def test_standard_includes_enabled(self, config):
        result = w.enabled_lenses(config, "standard")
        assert len(result) == 3  # simplification, standards, security (not drift)

    def test_deep_overrides_max_comments(self, config):
        config["deep_overrides"] = {"max_comments": 0}
        result = w.enabled_lenses(config, "deep")
        assert all(l["max_comments"] == 0 for l in result)

    def test_deep_default_unlimited(self, config):
        result = w.enabled_lenses(config, "deep")
        assert all(l["max_comments"] == 0 for l in result)


# ---------------------------------------------------------------------------
# build_review_prompt
# ---------------------------------------------------------------------------

class TestBuildReviewPrompt:
    def test_valid_prompt(self):
        prompt_dir = w.PROMPTS_DIR
        (prompt_dir / "security.md").write_text("You are a security reviewer.")
        result = w.build_review_prompt("security", "diff content", 5)
        assert "You are a security reviewer." in result
        assert "```diff\ndiff content\n```" in result
        assert "MAX COMMENTS: 5" in result

    def test_missing_prompt_file(self):
        assert w.build_review_prompt("nonexistent", "diff", 5) == ""

    def test_no_constraint_when_unlimited(self):
        prompt_dir = w.PROMPTS_DIR
        (prompt_dir / "deep.md").write_text("Deep review.")
        result = w.build_review_prompt("deep", "diff", 0)
        assert "MAX COMMENTS" not in result
        assert "Deep review." in result


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

class TestState:
    def test_load_empty(self):
        assert w.load_state("owner/repo", 1) == {}

    def test_save_load_roundtrip(self):
        data = {"last_head_sha": "abc", "last_reviewed_at": 123.4}
        w.save_state("owner/repo", 42, data)
        loaded = w.load_state("owner/repo", 42)
        assert loaded == data

    def test_repo_slash_in_filename(self):
        w.save_state("owner/repo", 1, {"key": "val"})
        expected = w.STATE_DIR / "owner_repo_pr1.json"
        assert expected.exists()

    def test_save_creates_dir(self, tmp_path, monkeypatch):
        nested = tmp_path / "deep" / "state"
        monkeypatch.setattr(core, "STATE_DIR", nested)
        monkeypatch.setattr(w, "STATE_DIR", nested)
        w.save_state("o/r", 1, {"x": 1})
        assert (nested / "o_r_pr1.json").exists()


class TestStateRace:
    """Verify the state race fix from Copilot review comments #1 and #2."""

    @patch.object(w, "clone_or_update")
    @patch.object(w, "checkout_pr")
    @patch.object(w, "get_diff", return_value="some diff")
    @patch.object(w, "get_head_sha", return_value="sha_after_review")
    @patch.object(w, "run_lens", return_value="")
    def test_check_comments_preserves_dispatch_state(
        self, _run, _sha, _diff, _checkout, _clone, config, tmp_path
    ):
        """check_comments must not overwrite last_head_sha set by dispatch_review."""
        _clone.return_value = tmp_path / "repos" / "fake"
        _clone.return_value.mkdir(parents=True, exist_ok=True)

        comments = [{"id": "c1", "body": "@pr-reviewer security"}]
        w.check_comments(config, "owner/repo", 1, comments)

        state = w.load_state("owner/repo", 1)
        # dispatch_review wrote last_head_sha; check_comments must preserve it
        assert state.get("last_head_sha") == "sha_after_review"
        # check_comments also wrote processed_comment_ids
        assert "c1" in state.get("processed_comment_ids", [])

    @patch.object(w, "clone_or_update")
    @patch.object(w, "checkout_pr")
    @patch.object(w, "get_diff", return_value="some diff")
    @patch.object(w, "get_head_sha", return_value="sha_new")
    @patch.object(w, "run_lens", return_value="")
    @patch.object(w, "gh_json")
    def test_poll_reloads_state_after_check_comments(
        self, mock_gh_json, _run, _sha, _diff, _checkout, _clone, config, tmp_path
    ):
        """poll dispatches exactly once for a single @pr-reviewer command."""
        _clone.return_value = tmp_path / "repos" / "fake"
        _clone.return_value.mkdir(parents=True, exist_ok=True)

        pr_data = [{
            "number": 1,
            "isDraft": False,
            "headRefOid": "sha_new",
            "comments": [{"id": "c1", "body": "@pr-reviewer"}],
        }]
        mock_gh_json.return_value = pr_data

        # check_comments dispatches once (for @pr-reviewer command).
        # poll should NOT dispatch again because state was updated.
        with patch.object(w, "dispatch_review", wraps=w.dispatch_review) as mock_dispatch:
            w.poll(config)

        assert mock_dispatch.call_count == 1


# ---------------------------------------------------------------------------
# read_secret
# ---------------------------------------------------------------------------

class TestReadSecret:
    def test_reads_from_file(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "my_secret"
        secret_file.write_text("hunter2\n")
        monkeypatch.setenv("my_secret_FILE", str(secret_file))
        assert w.read_secret("my_secret") == "hunter2"

    def test_placeholder_falls_through(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "tok"
        secret_file.write_text("PLACEHOLDER_for_ci")
        monkeypatch.setenv("tok_FILE", str(secret_file))
        monkeypatch.setenv("tok", "real_value")
        assert w.read_secret("tok") == "real_value"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("my_key", "from_env")
        assert w.read_secret("my_key") == "from_env"

    def test_required_missing_exits(self, monkeypatch):
        monkeypatch.delenv("missing_key", raising=False)
        with pytest.raises(SystemExit):
            w.read_secret("missing_key", required=True)

    def test_optional_missing_returns_empty(self, monkeypatch):
        monkeypatch.delenv("opt_key", raising=False)
        assert w.read_secret("opt_key", required=False) == ""

    def test_custom_file_env_override(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom_loc"
        custom.write_text("secret_val")
        monkeypatch.setenv("tok_FILE", str(custom))
        assert w.read_secret("tok") == "secret_val"


# ---------------------------------------------------------------------------
# check_comments
# ---------------------------------------------------------------------------

class TestCheckComments:
    @patch.object(w, "dispatch_review")
    def test_skips_already_processed(self, mock_dispatch, config):
        w.save_state("o/r", 1, {"processed_comment_ids": ["c1"]})
        comments = [{"id": "c1", "body": "@pr-reviewer"}]
        w.check_comments(config, "o/r", 1, comments)
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    def test_dispatches_new_command(self, mock_dispatch, config):
        comments = [{"id": "c1", "body": "@pr-reviewer security"}]
        w.check_comments(config, "o/r", 1, comments)
        mock_dispatch.assert_called_once_with(config, "o/r", 1, "security")

    @patch.object(w, "dispatch_review")
    def test_stop_no_dispatch(self, mock_dispatch, config):
        comments = [{"id": "c1", "body": "@pr-reviewer stop"}]
        w.check_comments(config, "o/r", 1, comments)
        mock_dispatch.assert_not_called()
        state = w.load_state("o/r", 1)
        assert "c1" in state["processed_comment_ids"]

    @patch.object(w, "dispatch_review")
    def test_ignores_non_commands(self, mock_dispatch, config):
        comments = [{"id": "c1", "body": "looks good to me!"}]
        w.check_comments(config, "o/r", 1, comments)
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    def test_multiple_commands_all_processed(self, mock_dispatch, config):
        comments = [
            {"id": "c1", "body": "@pr-reviewer security"},
            {"id": "c2", "body": "@pr-reviewer standards"},
            {"id": "c3", "body": "random"},
        ]
        w.check_comments(config, "o/r", 1, comments)
        assert mock_dispatch.call_count == 2
        state = w.load_state("o/r", 1)
        assert "c1" in state["processed_comment_ids"]
        assert "c2" in state["processed_comment_ids"]
        assert "c3" not in state["processed_comment_ids"]


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------

class TestPoll:
    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_skips_draft_prs(self, mock_gh_json, mock_dispatch, config):
        mock_gh_json.return_value = [
            {"number": 1, "isDraft": True, "headRefOid": "abc", "comments": []},
        ]
        w.poll(config)
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_owner_filter_rejects_mismatch(self, mock_gh_json, mock_dispatch, config):
        config["repos"] = ["other-owner/repo"]
        w.poll(config)
        mock_gh_json.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_writes_poll_timestamp(self, mock_gh_json, mock_dispatch, config):
        mock_gh_json.return_value = []
        w.poll(config)
        ts_file = w.STATE_DIR / "last_poll.json"
        assert ts_file.exists()
        data = json.loads(ts_file.read_text())
        assert abs(data["last_poll"] - time.time()) < 5

    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_no_auto_review_without_command(self, mock_gh_json, mock_dispatch, config):
        """On-demand only: new PRs without @pr-reviewer are NOT auto-reviewed."""
        mock_gh_json.return_value = [
            {"number": 7, "isDraft": False, "headRefOid": "sha1", "comments": []},
        ]
        w.poll(config)
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_reviews_when_command_present(self, mock_gh_json, mock_dispatch, config):
        """On-demand: reviews only when @pr-reviewer comment exists."""
        mock_gh_json.return_value = [
            {
                "number": 7,
                "isDraft": False,
                "headRefOid": "sha1",
                "comments": [{"id": "c1", "body": "@pr-reviewer"}],
            },
        ]
        w.poll(config)
        mock_dispatch.assert_called_once_with(config, "owner/repo-a", 7, "standard")


# ---------------------------------------------------------------------------
# gh helper
# ---------------------------------------------------------------------------

class TestGhHelper:
    @patch("subprocess.run")
    def test_builds_command_with_repo(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="output")
        result = w.gh(["pr", "list"], repo="owner/repo")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["gh", "--repo", "owner/repo", "pr", "list"]
        assert result == "output"

    @patch("subprocess.run")
    def test_builds_command_without_repo(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        w.gh(["version"])
        cmd = mock_run.call_args[0][0]
        assert cmd == ["gh", "version"]

    @patch("subprocess.run")
    def test_returns_empty_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        assert w.gh(["bad"]) == ""

    @patch("subprocess.run")
    def test_gh_json_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='[{"n": 1}]')
        result = w.gh_json(["pr", "list"])
        assert result == [{"n": 1}]

    @patch("subprocess.run")
    def test_gh_json_returns_list_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="err")
        assert w.gh_json(["bad"]) == []


# ---------------------------------------------------------------------------
# run_lens model routing
# ---------------------------------------------------------------------------

class TestRunLens:
    @patch.object(core, "run_lens_claude", return_value="claude result")
    def test_defaults_to_claude(self, mock_claude, config, tmp_path):
        prompt_dir = core.PROMPTS_DIR
        (prompt_dir / "simplification.md").write_text("prompt")
        lens = {"name": "simplification", "max_comments": 5}
        result = core.run_lens(lens, "diff", tmp_path, config)
        assert result == "claude result"
        mock_claude.assert_called_once()

    @patch.object(core, "run_lens_gemini", return_value="gemini result")
    def test_routes_to_gemini(self, mock_gemini, config, tmp_path):
        prompt_dir = core.PROMPTS_DIR
        (prompt_dir / "security.md").write_text("prompt")
        lens = {"name": "security", "max_comments": 5}
        result = core.run_lens(lens, "diff", tmp_path, config)
        assert result == "gemini result"

    def test_missing_prompt_returns_empty(self, config, tmp_path):
        lens = {"name": "nonexistent", "max_comments": 5}
        assert core.run_lens(lens, "diff", tmp_path, config) == ""

    @patch.object(core, "run_lens_claude", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300))
    def test_timeout_returns_empty(self, _mock, config, tmp_path):
        prompt_dir = core.PROMPTS_DIR
        (prompt_dir / "simplification.md").write_text("prompt")
        lens = {"name": "simplification", "max_comments": 5}
        result = core.run_lens(lens, "diff", tmp_path, config)
        assert result == ""


# ---------------------------------------------------------------------------
# post_review
# ---------------------------------------------------------------------------

class TestPostReview:
    @patch("subprocess.run")
    def test_adds_header_with_icon(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        w.post_review("o/r", 1, "security", "found issues")
        body_sent = mock_run.call_args.kwargs["input"]
        assert "Security Review" in body_sent
        assert "\U0001f512" in body_sent  # 🔒
        assert "found issues" in body_sent

    @patch("subprocess.run")
    def test_uses_stdin_for_body(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        w.post_review("o/r", 1, "standards", "body")
        cmd = mock_run.call_args[0][0]
        assert "--body-file" in cmd
        assert "-" in cmd


# ---------------------------------------------------------------------------
# save_poll_timestamp
# ---------------------------------------------------------------------------

class TestSavePollTimestamp:
    def test_writes_timestamp(self):
        w.save_poll_timestamp()
        ts_file = w.STATE_DIR / "last_poll.json"
        data = json.loads(ts_file.read_text())
        assert abs(data["last_poll"] - time.time()) < 2


# ---------------------------------------------------------------------------
# GitHubAppAuth
# ---------------------------------------------------------------------------

class TestGitHubAppAuth:
    def test_get_token_calls_refresh_when_no_token(self):
        auth = w.GitHubAppAuth(123, 456, "fake-key")
        with patch.object(auth, "_refresh") as mock_refresh:
            def set_token():
                auth._token = "tok123"
                auth._expires_at = time.time() + 3600
            mock_refresh.side_effect = set_token
            token = auth.get_token()
            mock_refresh.assert_called_once()
            assert token == "tok123"

    def test_get_token_uses_cache_when_valid(self):
        auth = w.GitHubAppAuth(123, 456, "fake-key")
        auth._token = "cached"
        auth._expires_at = time.time() + 3600  # valid for another hour
        with patch.object(auth, "_refresh") as mock_refresh:
            token = auth.get_token()
            mock_refresh.assert_not_called()
            assert token == "cached"

    def test_get_token_refreshes_when_near_expiry(self):
        auth = w.GitHubAppAuth(123, 456, "fake-key")
        auth._token = "old"
        auth._expires_at = time.time() + 100  # within 5min buffer
        with patch.object(auth, "_refresh") as mock_refresh:
            def set_token():
                auth._token = "new"
                auth._expires_at = time.time() + 3600
            mock_refresh.side_effect = set_token
            token = auth.get_token()
            mock_refresh.assert_called_once()
            assert token == "new"

    def test_get_token_raises_on_failed_refresh(self):
        auth = w.GitHubAppAuth(123, 456, "fake-key")
        with patch.object(auth, "_refresh"):  # _refresh does nothing → token stays None
            with pytest.raises(RuntimeError, match="Failed to obtain"):
                auth.get_token()


# ---------------------------------------------------------------------------
# parse_inline_comments
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
diff --git a/ansible/tasks/foo.yml b/ansible/tasks/foo.yml
--- a/ansible/tasks/foo.yml
+++ b/ansible/tasks/foo.yml
@@ -10,6 +10,8 @@
   name: Existing task
   command: echo hello
+  register: _result
+  changed_when: false

 - name: Another task
   command: echo world
diff --git a/services/bar.yml b/services/bar.yml
--- a/services/bar.yml
+++ b/services/bar.yml
@@ -1,3 +1,5 @@
 version: "3"
+services:
+  web:
   image: nginx
"""


class TestParseInlineComments:
    def test_basic_finding(self):
        body = '### [ansible/tasks/foo.yml:12] Unnecessary register\n\nThis register is unused.'
        comments = w.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 1
        assert comments[0]["path"] == "ansible/tasks/foo.yml"
        assert comments[0]["line"] == 12
        assert "unused" in comments[0]["body"]

    def test_multiple_findings(self):
        body = (
            '### [ansible/tasks/foo.yml:12] First\n\nBody one.\n\n'
            '### [services/bar.yml:2] Second\n\nBody two.'
        )
        comments = w.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 2
        assert comments[0]["path"] == "ansible/tasks/foo.yml"
        assert comments[1]["path"] == "services/bar.yml"

    def test_severity_prefix_parsed(self):
        body = '### [CRITICAL] [ansible/tasks/foo.yml:12] Bad thing\n\nExplanation.'
        comments = w.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 1
        assert comments[0]["line"] == 12

    def test_line_not_in_diff_skipped(self):
        body = '### [ansible/tasks/foo.yml:99] Not in diff\n\nShould be skipped.'
        comments = w.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 0

    def test_nearby_line_fuzzy_match(self):
        # Line 16 is not in diff (lines 10-15 are), but 15 is within offset 1
        body = '### [ansible/tasks/foo.yml:16] Close enough\n\nFuzzy.'
        comments = w.parse_inline_comments(body, SAMPLE_DIFF)
        assert len(comments) == 1
        assert comments[0]["line"] == 15

    def test_no_findings_returns_empty(self):
        body = 'This review has no structured findings.'
        assert w.parse_inline_comments(body, SAMPLE_DIFF) == []

    def test_empty_diff(self):
        body = '### [foo.py:1] Something\n\nBody.'
        assert w.parse_inline_comments(body, "") == []

    def test_deleted_lines_not_in_diff_set(self):
        diff = """\
diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -1,3 +1,2 @@
 keep
-removed
 also_keep
"""
        body = '### [f.py:1] On kept line\n\nOK.'
        comments = w.parse_inline_comments(body, diff)
        assert len(comments) == 1
        assert comments[0]["line"] == 1


# ---------------------------------------------------------------------------
# post_inline_review
# ---------------------------------------------------------------------------

class TestPostInlineReview:
    def test_success(self):
        comments = [{"path": "foo.py", "line": 10, "body": "Issue here"}]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = w.post_inline_review("owner/repo", 42, "security", comments, "abc123")
        assert result is True
        call_args = mock_run.call_args
        payload = json.loads(call_args.kwargs.get("input", call_args[1].get("input", "")))
        assert payload["commit_id"] == "abc123"
        assert payload["event"] == "COMMENT"
        assert len(payload["comments"]) == 1

    def test_failure_returns_false(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="err")
            result = w.post_inline_review("owner/repo", 42, "standards", [], "abc")
        assert result is False

    def test_review_body_includes_lens_name(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            w.post_inline_review("o/r", 1, "architecture", [{"path": "f", "line": 1, "body": "x"}], "sha")
        payload = json.loads(mock_run.call_args.kwargs.get("input", mock_run.call_args[1].get("input", "")))
        assert "Architecture" in payload["body"]
        assert "\U0001f3db" in payload["body"]


# ---------------------------------------------------------------------------
# post_review with inline fallback
# ---------------------------------------------------------------------------

class TestPostReviewInlineFallback:
    def test_tries_inline_first(self):
        body = '### [ansible/tasks/foo.yml:12] Finding\n\nDetail.'
        with patch.object(core, "parse_inline_comments", return_value=[{"path": "f", "line": 12, "body": "x"}]) as mock_parse, \
             patch.object(w, "get_head_sha", return_value="sha123"), \
             patch.object(w, "post_inline_review", return_value=True) as mock_inline:
            w.post_review("o/r", 1, "security", body, diff=SAMPLE_DIFF)
        mock_parse.assert_called_once()
        mock_inline.assert_called_once()

    def test_falls_back_to_comment_on_no_inline(self):
        with patch.object(core, "parse_inline_comments", return_value=[]), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            w.post_review("o/r", 1, "security", "No findings format", diff=SAMPLE_DIFF)
        # Should have called gh pr comment
        assert any("pr" in str(c) for c in mock_run.call_args_list)

    def test_falls_back_when_no_diff(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            w.post_review("o/r", 1, "security", "Body text", diff="")
        assert mock_run.called


    def test_refresh_passes_string_iss_to_jwt(self):
        """PyJWT 2.x requires iss to be a string — regression guard."""
        import sys
        import types

        mock_jwt = types.ModuleType("jwt")
        mock_jwt.encode = MagicMock(return_value="fake-jwt")
        sys.modules["jwt"] = mock_jwt
        try:
            auth = w.GitHubAppAuth(123, 456, "fake-key")
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = mock_urlopen.return_value.__enter__.return_value
                mock_resp.read.return_value = json.dumps(
                    {"token": "inst-tok", "expires_at": "2099-01-01T00:00:00Z"}
                ).encode()
                auth._refresh()
                payload = mock_jwt.encode.call_args[0][0]
                assert isinstance(payload["iss"], str)
                assert payload["iss"] == "123"
        finally:
            del sys.modules["jwt"]
