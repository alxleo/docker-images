"""Tests for gitea_webhook.py — webhook handler logic, no live Gitea needed."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

import review_core as core
import gitea_webhook as gw


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    for mod in (core, gw):
        if hasattr(mod, "STATE_DIR"):
            monkeypatch.setattr(mod, "STATE_DIR", tmp_path / "state")
        if hasattr(mod, "REPOS_DIR"):
            monkeypatch.setattr(mod, "REPOS_DIR", tmp_path / "repos")
        if hasattr(mod, "PROMPTS_DIR"):
            monkeypatch.setattr(mod, "PROMPTS_DIR", tmp_path / "prompts")
    monkeypatch.setattr(core, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(core, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(core, "PROMPTS_DIR", tmp_path / "prompts")
    (tmp_path / "state").mkdir()
    (tmp_path / "repos").mkdir()
    (tmp_path / "prompts").mkdir()


@pytest.fixture()
def config():
    return {
        "auto_lenses": ["simplification", "security"],
        "lenses": {
            "simplification": {"max_comments": 5},
            "security": {"max_comments": 5},
            "standards": {"max_comments": 5},
        },
    }


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------

class TestVerifySignature:
    def test_valid_signature(self, monkeypatch):
        monkeypatch.setattr(gw, "WEBHOOK_SECRET", "secret123")
        body = b'{"action": "opened"}'
        sig = hmac.new(b"secret123", body, hashlib.sha256).hexdigest()
        assert gw.verify_signature(body, sig) is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setattr(gw, "WEBHOOK_SECRET", "secret123")
        assert gw.verify_signature(b"body", "bad") is False

    def test_no_secret_configured(self, monkeypatch):
        monkeypatch.setattr(gw, "WEBHOOK_SECRET", "")
        assert gw.verify_signature(b"anything", "") is True


# ---------------------------------------------------------------------------
# handle_push
# ---------------------------------------------------------------------------

class TestHandlePush:
    def test_skips_main_branch(self, config):
        payload = {"ref": "refs/heads/main", "repository": {"name": "repo", "owner": {"login": "ci"}}}
        with patch.object(gw, "gitea_client") as mock_client:
            gw.handle_push(config, payload)
            mock_client.assert_not_called()

    def test_skips_non_branch_refs(self, config):
        payload = {"ref": "refs/tags/v1.0", "repository": {"name": "repo", "owner": {"login": "ci"}}}
        with patch.object(gw, "gitea_client") as mock_client:
            gw.handle_push(config, payload)
            mock_client.assert_not_called()

    def test_creates_pr_for_branch(self, config):
        payload = {
            "ref": "refs/heads/feat/new-thing",
            "repository": {"name": "myrepo", "owner": {"login": "ci"}},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        # No existing PRs
        mock_client.get.return_value = MagicMock(status_code=200, json=MagicMock(return_value=[]))
        # PR creation succeeds
        mock_client.post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"number": 5}),
        )
        with patch.object(gw, "gitea_client", return_value=mock_client):
            gw.handle_push(config, payload)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "pulls" in call_args[0][0]
        assert call_args[1]["json"]["head"] == "feat/new-thing"

    def test_skips_if_pr_exists(self, config):
        payload = {
            "ref": "refs/heads/fix/bug",
            "repository": {"name": "myrepo", "owner": {"login": "ci"}},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        # Existing PR for this branch
        mock_client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{"number": 3, "head": {"ref": "fix/bug"}}]),
        )
        with patch.object(gw, "gitea_client", return_value=mock_client):
            gw.handle_push(config, payload)

        mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# handle_pull_request
# ---------------------------------------------------------------------------

class TestHandlePullRequest:
    def test_auto_reviews_on_opened(self, config):
        payload = {
            "action": "opened",
            "pull_request": {"number": 7, "head": {"sha": "abc123"}},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_pull_request(config, payload)
            mock_exec.submit.assert_called_once()
            # submit(dispatch_review, config, owner, repo, pr_number, head_sha, depth)
            args = mock_exec.submit.call_args[0]
            assert args[0] == gw.dispatch_review
            assert args[4] == 7  # pr_number
            assert args[5] == "abc123"  # head_sha
            assert args[6] == "auto"  # depth

    def test_auto_reviews_on_synchronized(self, config):
        payload = {
            "action": "synchronized",
            "pull_request": {"number": 7, "head": {"sha": "def456"}},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_pull_request(config, payload)
            mock_exec.submit.assert_called_once()

    def test_ignores_closed_action(self, config):
        payload = {
            "action": "closed",
            "pull_request": {"number": 7, "head": {"sha": "abc"}},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_pull_request(config, payload)
            mock_exec.submit.assert_not_called()

    def test_skips_already_reviewed_sha(self, config):
        core.save_state("ci/repo", 7, {"last_head_sha": "abc123"})
        payload = {
            "action": "synchronized",
            "pull_request": {"number": 7, "head": {"sha": "abc123"}},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_pull_request(config, payload)
            mock_exec.submit.assert_not_called()


# ---------------------------------------------------------------------------
# handle_issue_comment
# ---------------------------------------------------------------------------

class TestHandleIssueComment:
    def test_dispatches_on_command(self, config):
        payload = {
            "issue": {
                "number": 3,
                "pull_request": {"head": {"sha": "sha1"}},
            },
            "comment": {"id": 42, "body": "@pr-reviewer security"},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_issue_comment(config, payload)
            mock_exec.submit.assert_called_once()
            # submit(dispatch_review, config, owner, repo, pr_number, head_sha, depth)
            args = mock_exec.submit.call_args[0]
            assert args[6] == "security"

    def test_ignores_non_pr_issue(self, config):
        payload = {
            "issue": {"number": 3},  # no pull_request key
            "comment": {"id": 42, "body": "@pr-reviewer"},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_issue_comment(config, payload)
            mock_exec.submit.assert_not_called()

    def test_ignores_non_command(self, config):
        payload = {
            "issue": {"number": 3, "pull_request": {}},
            "comment": {"id": 42, "body": "looks good!"},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_issue_comment(config, payload)
            mock_exec.submit.assert_not_called()

    def test_skips_already_processed_comment(self, config):
        core.save_state("ci/repo", 3, {"processed_comment_ids": ["42"]})
        payload = {
            "issue": {"number": 3, "pull_request": {"head": {"sha": "sha1"}}},
            "comment": {"id": 42, "body": "@pr-reviewer"},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_issue_comment(config, payload)
            mock_exec.submit.assert_not_called()

    def test_stop_command_no_dispatch(self, config):
        payload = {
            "issue": {"number": 3, "pull_request": {"head": {"sha": "sha1"}}},
            "comment": {"id": 99, "body": "@pr-reviewer stop"},
            "repository": {"name": "repo", "owner": {"login": "ci"}},
        }
        with patch.object(gw, "_executor") as mock_exec:
            gw.handle_issue_comment(config, payload)
            mock_exec.submit.assert_not_called()
        # But comment ID is still tracked
        state = core.load_state("ci/repo", 3)
        assert "99" in state["processed_comment_ids"]


# ---------------------------------------------------------------------------
# ensure_pr
# ---------------------------------------------------------------------------

class TestEnsurePr:
    def test_returns_existing_pr(self):
        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{"number": 5, "head": {"ref": "feat/x"}}]),
        )
        result = gw.ensure_pr(mock_client, "ci", "repo", "feat/x")
        assert result == 5
        mock_client.post.assert_not_called()

    def test_creates_new_pr(self):
        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value=[]),
        )
        mock_client.post.return_value = MagicMock(
            status_code=201, json=MagicMock(return_value={"number": 10}),
        )
        result = gw.ensure_pr(mock_client, "ci", "repo", "fix/bug")
        assert result == 10

    def test_returns_none_on_failure(self):
        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value=[]),
        )
        mock_client.post.return_value = MagicMock(
            status_code=409, text="conflict",
        )
        result = gw.ensure_pr(mock_client, "ci", "repo", "bad/branch")
        assert result is None


# ---------------------------------------------------------------------------
# post_review
# ---------------------------------------------------------------------------

class TestPostReview:
    def test_inline_review_success(self):
        mock_client = MagicMock()
        mock_client.post.return_value = MagicMock(status_code=201)

        diff = """\
diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -1,3 +1,5 @@
 keep
+new_line
+another
 end
"""
        body = "### [f.py:2] Issue\n\nDetail."
        gw.post_review(mock_client, "ci", "repo", 1, "security", body, "sha1", diff=diff)

        # Should have tried inline review (POST to /reviews)
        call_args = mock_client.post.call_args
        assert "reviews" in call_args[0][0]

    def test_fallback_to_comment(self):
        mock_client = MagicMock()
        # Inline fails, then comment succeeds
        mock_client.post.side_effect = [
            MagicMock(status_code=500),  # inline review fails
            MagicMock(status_code=201),  # comment succeeds
        ]

        diff = """\
diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -1,3 +1,5 @@
 keep
+new
 end
"""
        body = "### [f.py:2] Issue\n\nDetail."
        gw.post_review(mock_client, "ci", "repo", 1, "security", body, "sha1", diff=diff)

        assert mock_client.post.call_count == 2
        second_call = mock_client.post.call_args_list[1]
        assert "comments" in second_call[0][0]

    def test_comment_without_diff(self):
        mock_client = MagicMock()
        mock_client.post.return_value = MagicMock(status_code=201)

        gw.post_review(mock_client, "ci", "repo", 1, "simplification", "Review body.", "sha1")

        call_args = mock_client.post.call_args
        assert "comments" in call_args[0][0]
        assert "Simplification Review" in call_args[1]["json"]["body"]
