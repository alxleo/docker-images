"""
Unit tests for mcp/entrypoint.py — pure Python, no Docker.

Tests command construction, filter arg building, server command
resolution, secret injection, and startup jitter.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import entrypoint from mcp/ (not a package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
import entrypoint


# Helper to clear all MCP-related env vars between tests
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove all MCP env vars and secret state so tests start clean."""
    for var in [
        "MCP_SERVER_COMMAND",
        "MCP_PACKAGE_NAME",
        "MCP_ENTRYPOINT_NAME",
        "MCP_PORT",
        "MCP_API_KEY",
        "MCP_STARTUP_JITTER",
        "MCP_CONNECTION_TIMEOUT",
        "FILTER_INCLUDE",
        "FILTER_EXCLUDE",
    ]:
        monkeypatch.delenv(var, raising=False)
    entrypoint._secret_values.clear()


# =========================================================================
# build_filter_args()
# =========================================================================


class TestBuildFilterArgs:
    def test_no_filter(self):
        assert entrypoint.build_filter_args() == []

    def test_include_only(self, monkeypatch):
        monkeypatch.setenv("FILTER_INCLUDE", "tool1 tool2")
        assert entrypoint.build_filter_args() == [
            "mcp-filter", "--include", "tool1", "--include", "tool2",
        ]

    def test_exclude_only(self, monkeypatch):
        monkeypatch.setenv("FILTER_EXCLUDE", "bad")
        assert entrypoint.build_filter_args() == [
            "mcp-filter", "--exclude", "bad",
        ]

    def test_both_include_and_exclude(self, monkeypatch):
        monkeypatch.setenv("FILTER_INCLUDE", "good")
        monkeypatch.setenv("FILTER_EXCLUDE", "bad")
        result = entrypoint.build_filter_args()
        assert result[0] == "mcp-filter"
        assert "--include" in result
        assert "--exclude" in result
        assert result.index("--include") < result.index("--exclude")

    def test_empty_strings(self, monkeypatch):
        monkeypatch.setenv("FILTER_INCLUDE", "")
        monkeypatch.setenv("FILTER_EXCLUDE", "")
        assert entrypoint.build_filter_args() == []

    def test_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("FILTER_INCLUDE", "   ")
        assert entrypoint.build_filter_args() == []


# =========================================================================
# get_server_command()
# =========================================================================


class TestGetServerCommand:
    def test_explicit_override(self, monkeypatch):
        monkeypatch.setenv("MCP_SERVER_COMMAND", "custom-cmd --flag")
        assert entrypoint.get_server_command() == "custom-cmd --flag"

    def test_python_entrypoint(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "arxiv-mcp-server==0.3.2")
        monkeypatch.setenv("MCP_ENTRYPOINT_NAME", "arxiv-mcp-server")
        assert entrypoint.get_server_command() == "arxiv-mcp-server"

    def test_npm_with_bin_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "mcp-hacker-news@1.0.3")
        bin_file = tmp_path / "mcp-bin-name"
        bin_file.write_text("  mcp-hackernews  \n")
        monkeypatch.setattr(entrypoint, "BIN_NAME_FILE", bin_file)
        assert entrypoint.get_server_command() == "mcp-hackernews"

    def test_npm_fallback_unscoped(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "mcp-hacker-news@1.0.3")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        assert entrypoint.get_server_command() == "mcp-hacker-news"

    def test_npm_fallback_scoped(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "@upstash/context7-mcp@2.1.1")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        assert entrypoint.get_server_command() == "context7-mcp"

    def test_npm_fallback_scoped_no_version(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "@org/my-tool")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        assert entrypoint.get_server_command() == "my-tool"

    def test_npm_fallback_no_version(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "simple-package")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        assert entrypoint.get_server_command() == "simple-package"

    def test_missing_config_exits(self):
        with pytest.raises(SystemExit):
            entrypoint.get_server_command()


# =========================================================================
# build_mcp_command()
# =========================================================================


class TestBuildMCPCommand:
    def test_basic_command(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "mcp-hacker-news@1.0.3")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        cmd = entrypoint.build_mcp_command()
        assert cmd[0] == "mcp-proxy"
        assert "--port" in cmd
        assert cmd[cmd.index("--port") + 1] == "8080"
        assert "--connectionTimeout" in cmd
        assert "--shell" not in cmd
        assert "--" in cmd
        # Server command follows the -- separator
        sep_idx = cmd.index("--")
        assert cmd[sep_idx + 1] == "mcp-hacker-news"

    def test_with_api_key(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "mcp-hacker-news@1.0.3")
        monkeypatch.setenv("MCP_API_KEY", "test-secret-key")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        cmd = entrypoint.build_mcp_command()
        assert "--apiKey" in cmd
        assert cmd[cmd.index("--apiKey") + 1] == "test-secret-key"

    def test_with_filter(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "mcp-hacker-news@1.0.3")
        monkeypatch.setenv("FILTER_EXCLUDE", "dangerous_tool")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        cmd = entrypoint.build_mcp_command()
        assert "--shell" not in cmd
        # After --, the filter chain is: mcp-filter --exclude dangerous_tool -- mcp-hacker-news
        sep_idx = cmd.index("--")
        after_sep = cmd[sep_idx + 1:]
        assert after_sep[0] == "mcp-filter"
        assert "--exclude" in after_sep
        assert "dangerous_tool" in after_sep
        # Nested -- separates filter args from server command
        assert "--" in after_sep
        nested_sep = after_sep.index("--")
        assert "mcp-hacker-news" in after_sep[nested_sep + 1:]

    def test_complex_server_command_with_quotes(self, monkeypatch):
        """MCP_SERVER_COMMAND with quoted args (e.g., mcp-remote with headers) is split correctly."""
        monkeypatch.setenv(
            "MCP_SERVER_COMMAND",
            'npx mcp-remote@0.1.38 https://mcp.jina.ai/sse --header "Authorization: Bearer ${JINA_API_KEY}"',
        )
        cmd = entrypoint.build_mcp_command()
        sep_idx = cmd.index("--")
        after_sep = cmd[sep_idx + 1:]
        assert after_sep[0] == "npx"
        assert after_sep[1] == "mcp-remote@0.1.38"
        assert after_sep[2] == "https://mcp.jina.ai/sse"
        assert after_sep[3] == "--header"
        # shlex.split removes quotes but preserves the content as one token
        assert after_sep[4] == "Authorization: Bearer ${JINA_API_KEY}"

    def test_custom_port(self, monkeypatch):
        monkeypatch.setenv("MCP_PACKAGE_NAME", "mcp-hacker-news@1.0.3")
        monkeypatch.setenv("MCP_PORT", "9090")
        monkeypatch.setattr(
            entrypoint, "BIN_NAME_FILE", Path("/nonexistent/file")
        )
        cmd = entrypoint.build_mcp_command()
        assert cmd[cmd.index("--port") + 1] == "9090"


# =========================================================================
# main() — secrets + jitter
# =========================================================================


class TestMain:
    def test_secrets_injection(self, monkeypatch, tmp_path):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "api_key").write_text("my-secret-value\n")
        (secrets_dir / "other_token").write_text("  token-123  ")

        monkeypatch.setenv("MCP_SERVER_COMMAND", "echo")
        monkeypatch.setenv("MCP_STARTUP_JITTER", "0")

        # Redirect /run/secrets to our temp dir so main() reads our files
        original_path = entrypoint.Path
        monkeypatch.setattr(
            entrypoint, "Path",
            lambda p: secrets_dir if p == "/run/secrets" else original_path(p),
        )

        # Call actual main(), but prevent os.execvp from replacing the process
        with patch("os.execvp", side_effect=SystemExit(0)), pytest.raises(SystemExit):
            entrypoint.main()

        assert os.environ.get("API_KEY") == "my-secret-value"
        assert os.environ.get("OTHER_TOKEN") == "token-123"

        # Cleanup env vars set directly by main() (not tracked by monkeypatch)
        os.environ.pop("API_KEY", None)
        os.environ.pop("OTHER_TOKEN", None)

    def test_secrets_missing_dir(self, monkeypatch):
        """No /run/secrets dir should not crash."""
        monkeypatch.setenv("MCP_SERVER_COMMAND", "echo")
        monkeypatch.setenv("MCP_STARTUP_JITTER", "0")

        with patch("os.execvp", side_effect=SystemExit(0)), pytest.raises(SystemExit):
            entrypoint.main()

    def test_jitter_disabled(self, monkeypatch):
        monkeypatch.setenv("MCP_SERVER_COMMAND", "echo")
        monkeypatch.setenv("MCP_STARTUP_JITTER", "0")

        with patch("time.sleep") as mock_sleep, \
             patch("os.execvp", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                entrypoint.main()
            mock_sleep.assert_not_called()

    def test_jitter_enabled(self, monkeypatch):
        monkeypatch.setenv("MCP_SERVER_COMMAND", "echo")
        monkeypatch.setenv("MCP_STARTUP_JITTER", "5")

        with patch("time.sleep") as mock_sleep, \
             patch("os.execvp", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                entrypoint.main()
            mock_sleep.assert_called_once()
            delay = mock_sleep.call_args[0][0]
            assert 0 <= delay <= 5

    def test_secrets_redacted_in_output(self, monkeypatch, tmp_path, capsys):
        """Secret values loaded from /run/secrets/ are masked in command output."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "jina_api_key").write_text("sk-super-secret-token-12345\n")

        monkeypatch.setenv(
            "MCP_SERVER_COMMAND",
            'npx mcp-remote https://mcp.jina.ai/sse --header "Authorization: Bearer sk-super-secret-token-12345"',
        )
        monkeypatch.setenv("MCP_STARTUP_JITTER", "0")

        original_path = entrypoint.Path
        monkeypatch.setattr(
            entrypoint, "Path",
            lambda p: secrets_dir if p == "/run/secrets" else original_path(p),
        )

        with patch("os.execvp", side_effect=SystemExit(0)), pytest.raises(SystemExit):
            entrypoint.main()

        captured = capsys.readouterr()
        # The full secret must NOT appear in output
        assert "sk-super-secret-token-12345" not in captured.out
        # But the redacted form (first 2 chars + ***) should
        assert "sk***" in captured.out

        os.environ.pop("JINA_API_KEY", None)

    def test_short_secrets_not_redacted(self, monkeypatch, tmp_path, capsys):
        """Secrets <= 4 chars are not redacted (too short, would cause false positives)."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "pin").write_text("1234")

        monkeypatch.setenv("MCP_SERVER_COMMAND", "echo 1234")
        monkeypatch.setenv("MCP_STARTUP_JITTER", "0")

        original_path = entrypoint.Path
        monkeypatch.setattr(
            entrypoint, "Path",
            lambda p: secrets_dir if p == "/run/secrets" else original_path(p),
        )

        with patch("os.execvp", side_effect=SystemExit(0)), pytest.raises(SystemExit):
            entrypoint.main()

        captured = capsys.readouterr()
        # Short secret should NOT be redacted (len <= 4)
        assert "1234" in captured.out

        os.environ.pop("PIN", None)
