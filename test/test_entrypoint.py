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
import entrypoint  # noqa: E402


# Helper to clear all MCP-related env vars between tests
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove all MCP env vars so tests start from a clean state."""
    for var in [
        "MCP_SERVER_COMMAND",
        "MCP_PACKAGE_NAME",
        "MCP_ENTRYPOINT_NAME",
        "MCP_PORT",
        "MCP_API_KEY",
        "MCP_STARTUP_JITTER",
        "FILTER_INCLUDE",
        "FILTER_EXCLUDE",
    ]:
        monkeypatch.delenv(var, raising=False)


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
        assert "--shell" in cmd
        assert cmd[-1] == "mcp-hacker-news"

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
        shell_cmd = cmd[cmd.index("--shell") + 1]
        assert "mcp-filter" in shell_cmd
        assert "--exclude" in shell_cmd
        assert "dangerous_tool" in shell_cmd
        assert " -- " in shell_cmd
        assert "mcp-hacker-news" in shell_cmd

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
        with patch("os.execvp", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                entrypoint.main()

        assert os.environ.get("API_KEY") == "my-secret-value"
        assert os.environ.get("OTHER_TOKEN") == "token-123"

        # Cleanup to avoid leaking env vars to other tests
        del os.environ["API_KEY"]
        del os.environ["OTHER_TOKEN"]

    def test_secrets_missing_dir(self, monkeypatch):
        """No /run/secrets dir should not crash."""
        monkeypatch.setenv("MCP_SERVER_COMMAND", "echo")
        monkeypatch.setenv("MCP_STARTUP_JITTER", "0")

        with patch("os.execvp", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
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
