"""Unit tests for gh-watcher.py — pure logic, no Docker/GitHub/AI CLIs needed."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import gh_watcher as w


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Redirect all module-level paths to tmp dirs."""
    monkeypatch.setattr(w, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(w, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(w, "PROMPTS_DIR", tmp_path / "prompts")
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
        assert w.parse_command("@review") == "standard"

    def test_deep(self):
        assert w.parse_command("@review deep") == "deep"

    def test_security(self):
        assert w.parse_command("@review security") == "security"

    def test_standards(self):
        assert w.parse_command("@review standards") == "standards"

    def test_drift(self):
        assert w.parse_command("@review drift") == "drift"

    def test_simplification(self):
        assert w.parse_command("@review simplification") == "simplification"

    def test_quick(self):
        assert w.parse_command("@review quick") == "quick"

    def test_stop(self):
        assert w.parse_command("@review stop") == "stop"

    def test_random_text_returns_none(self):
        assert w.parse_command("just a regular comment") is None

    def test_whitespace_stripped(self):
        assert w.parse_command("  @review  ") == "standard"

    def test_trailing_text_still_matches(self):
        assert w.parse_command("@review deep please look at auth") == "deep"

    def test_case_insensitive(self):
        assert w.parse_command("@Review Deep") == "deep"

    def test_empty_string(self):
        assert w.parse_command("") is None

    def test_partial_prefix_no_match(self):
        assert w.parse_command("@rev") is None


# ---------------------------------------------------------------------------
# needs_review
# ---------------------------------------------------------------------------

class TestNeedsReview:
    def test_empty_state_needs_review(self):
        assert w.needs_review("r", {"headRefOid": "abc"}, {}) is True

    def test_same_sha_no_review(self):
        state = {"last_head_sha": "abc123"}
        pr = {"headRefOid": "abc123"}
        assert w.needs_review("r", pr, state) is False

    def test_different_sha_needs_review(self):
        state = {"last_head_sha": "old"}
        pr = {"headRefOid": "new"}
        assert w.needs_review("r", pr, state) is True

    def test_pr_missing_sha_no_review(self):
        state = {"last_head_sha": "abc"}
        pr = {}
        assert w.needs_review("r", pr, state) is False

    def test_state_missing_sha_key(self):
        state = {"last_reviewed_at": 123}
        pr = {"headRefOid": "abc"}
        assert w.needs_review("r", pr, state) is True


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

        comments = [{"id": "c1", "body": "@review security"}]
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
        """poll must reload state after check_comments to avoid double review."""
        _clone.return_value = tmp_path / "repos" / "fake"
        _clone.return_value.mkdir(parents=True, exist_ok=True)

        pr_data = [{
            "number": 1,
            "isDraft": False,
            "headRefOid": "sha_new",
            "comments": [{"id": "c1", "body": "@review"}],
        }]
        mock_gh_json.return_value = pr_data

        # Track how many times dispatch_review is called
        call_count = {"n": 0}
        original_dispatch = w.dispatch_review

        def counting_dispatch(*args, **kwargs):
            call_count["n"] += 1
            return original_dispatch(*args, **kwargs)

        with patch.object(w, "dispatch_review", side_effect=counting_dispatch):
            w.poll(config)

        # check_comments dispatches once (for @review command).
        # poll should NOT dispatch again because state was updated.
        assert call_count["n"] == 1


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
        comments = [{"id": "c1", "body": "@review"}]
        w.check_comments(config, "o/r", 1, comments)
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    def test_dispatches_new_command(self, mock_dispatch, config):
        comments = [{"id": "c1", "body": "@review security"}]
        w.check_comments(config, "o/r", 1, comments)
        mock_dispatch.assert_called_once_with(config, "o/r", 1, "security")

    @patch.object(w, "dispatch_review")
    def test_stop_no_dispatch(self, mock_dispatch, config):
        comments = [{"id": "c1", "body": "@review stop"}]
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
            {"id": "c1", "body": "@review security"},
            {"id": "c2", "body": "@review standards"},
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
    def test_auto_reviews_new_pr(self, mock_gh_json, mock_dispatch, config):
        mock_gh_json.return_value = [
            {"number": 7, "isDraft": False, "headRefOid": "sha1", "comments": []},
        ]
        w.poll(config)
        mock_dispatch.assert_called_once_with(config, "owner/repo-a", 7, "standard")

    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_skips_reviewed_pr_same_sha(self, mock_gh_json, mock_dispatch, config):
        w.save_state("owner/repo-a", 7, {"last_head_sha": "sha1"})
        mock_gh_json.return_value = [
            {"number": 7, "isDraft": False, "headRefOid": "sha1", "comments": []},
        ]
        w.poll(config)
        mock_dispatch.assert_not_called()

    @patch.object(w, "dispatch_review")
    @patch.object(w, "gh_json")
    def test_re_reviews_on_new_commits(self, mock_gh_json, mock_dispatch, config):
        w.save_state("owner/repo-a", 7, {"last_head_sha": "old_sha"})
        mock_gh_json.return_value = [
            {"number": 7, "isDraft": False, "headRefOid": "new_sha", "comments": []},
        ]
        w.poll(config)
        mock_dispatch.assert_called_once()


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
    @patch.object(w, "run_lens_claude", return_value="claude result")
    def test_defaults_to_claude(self, mock_claude, config, tmp_path):
        prompt_dir = w.PROMPTS_DIR
        (prompt_dir / "simplification.md").write_text("prompt")
        lens = {"name": "simplification", "max_comments": 5}
        result = w.run_lens(lens, "diff", tmp_path, config)
        assert result == "claude result"
        mock_claude.assert_called_once()

    @patch.object(w, "run_lens_gemini", return_value="gemini result")
    def test_routes_to_gemini(self, mock_gemini, config, tmp_path):
        prompt_dir = w.PROMPTS_DIR
        (prompt_dir / "security.md").write_text("prompt")
        lens = {"name": "security", "max_comments": 5}
        result = w.run_lens(lens, "diff", tmp_path, config)
        assert result == "gemini result"

    def test_missing_prompt_returns_empty(self, config, tmp_path):
        lens = {"name": "nonexistent", "max_comments": 5}
        assert w.run_lens(lens, "diff", tmp_path, config) == ""

    @patch.object(w, "run_lens_claude", side_effect=TimeoutError)
    def test_timeout_returns_empty(self, _mock, config, tmp_path):
        prompt_dir = w.PROMPTS_DIR
        (prompt_dir / "simplification.md").write_text("prompt")
        lens = {"name": "simplification", "max_comments": 5}
        # subprocess.TimeoutExpired is caught, not generic TimeoutError
        # but the function catches subprocess.TimeoutExpired specifically
        # Let's test with the right exception
        _mock.side_effect = __import__("subprocess").TimeoutExpired(cmd="claude", timeout=300)
        result = w.run_lens(lens, "diff", tmp_path, config)
        assert result == ""


# ---------------------------------------------------------------------------
# post_review
# ---------------------------------------------------------------------------

class TestPostReview:
    @patch("subprocess.run")
    def test_adds_header_with_icon(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        w.post_review("o/r", 1, "security", "found issues")
        call_kwargs = mock_run.call_args
        body_sent = call_kwargs.kwargs.get("input") or call_kwargs[1].get("input")
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
