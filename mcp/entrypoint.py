#!/usr/bin/env python3
"""
MCP Service Entrypoint

Purpose:
  - Orchestrates mcp-proxy + optional tool filtering + MCP server
  - Builds command from environment variables
  - Provides clear error messages

Environment Variables:
  MCP_SERVER_COMMAND: Full command override (e.g., "mcp-hackernews")
  MCP_PACKAGE_NAME: npm package (globally installed at build time, e.g., "mcp-hackernews@1.0.3")
  MCP_PORT: Port to listen on (default: 8080)
  MCP_API_KEY: Optional API key for authentication
  FILTER_INCLUDE: Space-separated tools to include (e.g., "search get_info")
  FILTER_EXCLUDE: Space-separated tools to exclude (e.g., "delete_post create_post")

Secrets can be provided via:
  - Docker Compose native secrets (/run/secrets/ files, preferred)
  - env_file at compose level (secret injection, backwards compat)
No runtime secret fetching - all secrets are pre-injected before container start.
"""

import os
import random
import sys
import shlex
import time
from pathlib import Path


def print_header(title: str):
    """Print a formatted section header"""
    print("=" * 60)
    print(f"🚀 {title}")
    print("=" * 60)
    print()


def build_filter_args() -> list[str]:
    """
    Build mcp-filter command arguments from environment variables.

    Returns:
        List of filter command parts (e.g., ["mcp-filter", "--exclude", "tool1", "--exclude", "tool2"])
        Empty list if no filtering specified.
    """
    filter_include = os.getenv("FILTER_INCLUDE", "").split()
    filter_exclude = os.getenv("FILTER_EXCLUDE", "").split()

    if not (filter_include or filter_exclude):
        return []

    cmd = ["mcp-filter"]

    for tool in filter_include:
        cmd.extend(["--include", tool])

    for tool in filter_exclude:
        cmd.extend(["--exclude", tool])

    return cmd


def get_server_command() -> str:
    """
    Determine the MCP server command from environment variables.

    Handles both npm-based and Python-based MCP servers.

    Returns:
        Server command string

    Raises:
        SystemExit: If required environment variables are not set
    """
    # Explicit command override (highest priority)
    if server_cmd := os.getenv("MCP_SERVER_COMMAND"):
        return server_cmd

    # Python-based MCP (system-installed via uv pip install --system)
    # The entrypoint script is in /usr/local/bin/ from the image build
    if (package_name := os.getenv("MCP_PACKAGE_NAME")) and (entrypoint := os.getenv("MCP_ENTRYPOINT_NAME")):
        return entrypoint

    # npm-based MCP (globally installed at build time)
    if package_name := os.getenv("MCP_PACKAGE_NAME"):
        bin_name_file = Path("/usr/local/share/mcp-bin-name")
        if bin_name_file.exists():
            return bin_name_file.read_text().strip()
        # Fallback: derive bin name by stripping version and scope
        name = package_name.rsplit("@", 1)[0] if "@" in package_name and not package_name.startswith("@") else package_name
        if name.startswith("@"):
            # Scoped: @org/pkg@ver → strip version, then take pkg part
            name = name.rsplit("@", 1)[0]
            name = name.split("/", 1)[1]
        return name

    # No configuration found
    print()
    print("❌ ERROR: No MCP server specified!")
    print()
    print("Set one of:")
    print('  MCP_SERVER_COMMAND="npx mcp-hackernews" (explicit override)')
    print('  MCP_PACKAGE_NAME="mcp-hackernews@1.0.3" (npm package)')
    print('  MCP_PACKAGE_NAME + MCP_ENTRYPOINT_NAME (Python package)')
    print()
    sys.exit(1)


def build_mcp_command() -> list[str]:
    """
    Build the complete command to execute.

    Returns:
        Command as list suitable for os.execvp()
    """
    # Get server command
    server_cmd = get_server_command()

    # Add filtering if specified
    filter_args = build_filter_args()
    if filter_args:
        # Chain: mcp-filter -> actual MCP server
        # Build as shell command: "mcp-filter --exclude x -- npx mcp-hackernews"
        filter_str = " ".join(shlex.quote(arg) for arg in filter_args)
        full_server_cmd = f"{filter_str} -- {server_cmd}"
    else:
        full_server_cmd = server_cmd

    port = os.getenv("MCP_PORT", "8080")

    # mcp-proxy: globally installed, called directly (no npx overhead)
    # --connectionTimeout 120s (default 60s too short under mass-restart contention)
    proxy_cmd = ["mcp-proxy", "--port", port, "--connectionTimeout", "120000"]

    # Add API key if provided
    if api_key := os.getenv("MCP_API_KEY"):
        proxy_cmd.extend(["--apiKey", api_key])

    proxy_cmd.extend(["--shell", full_server_cmd])

    return proxy_cmd


def main():
    """Main entrypoint - build and execute MCP service command"""
    print_header("MCP Service Startup")

    # Load Docker Compose secrets into environment
    secrets_dir = Path('/run/secrets')
    if secrets_dir.is_dir():
        for secret_file in secrets_dir.iterdir():
            if secret_file.is_file():
                os.environ[secret_file.name.upper()] = secret_file.read_text().strip()

    # Build command
    cmd = build_mcp_command()

    # Startup jitter: spread mass restarts to avoid CPU/IO stampede
    # Set MCP_STARTUP_JITTER=0 to disable (e.g., local dev)
    max_jitter = int(os.getenv("MCP_STARTUP_JITTER", "10"))
    if max_jitter > 0:
        delay = random.uniform(0, max_jitter)
        print(f"Startup jitter: {delay:.1f}s")
        time.sleep(delay)

    print_header("Starting MCP Service")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)
    print()

    # Replace process with mcp-proxy (exec)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
