#!/usr/bin/env python3
"""Sync Claude Code plugins from marketplaces on container startup.

Reads plugin list from config.yml (plugins key) and ensures each is installed.
Runs `claude plugins marketplace update` to pull latest versions.
Idempotent — safe to run on every container start.

Expected config.yml structure:
    plugins:
      marketplaces:
        - anthropics/claude-plugins-official
        - trailofbits/skills
      install:
        - pr-review-toolkit@claude-plugins-official
        - code-review@claude-plugins-official
        - differential-review@trailofbits
      gemini_skills:
        - https://github.com/anthropics/claude-plugins-official
"""

import logging
import os
import subprocess
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync-plugins")

CONFIG_PATH = Path("/app/config.yml")


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    """Run a command, return (exit_code, combined output)."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output


def get_marketplaces() -> set[str]:
    """Get currently registered marketplace names."""
    rc, out = run(["claude", "plugins", "marketplace", "list"])
    names = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("❯ "):
            names.add(line.removeprefix("❯ ").strip())
    return names


def get_installed() -> set[str]:
    """Get currently installed plugin identifiers (name@marketplace)."""
    rc, out = run(["claude", "plugins", "list"])
    plugins = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("❯ "):
            plugins.add(line.removeprefix("❯ ").strip())
    return plugins


def setup_codex_auth():
    """Authenticate Codex CLI if OPENAI_API_KEY is set.

    Two auth paths:
    - Subscription: mount host's ~/.codex/auth.json (has OAuth refresh token)
    - API key: OPENAI_API_KEY env var → pipe through `codex login --with-api-key`

    Skips if auth.json already exists (mounted or from previous login).
    """
    auth_file = Path("/root/.codex/auth.json")
    if auth_file.exists():
        log.info("Codex auth.json present (mounted or cached)")
        return

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return

    log.info("Authenticating Codex CLI via API key...")
    result = subprocess.run(
        ["codex", "login", "--with-api-key"],
        input=api_key, capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode == 0:
        log.info("Codex authenticated")
    else:
        log.warning("Codex login failed (non-fatal): %s", result.stderr[:200])


def sync():
    # Authenticate Codex if key is available (must happen before plugin sync)
    setup_codex_auth()

    if not CONFIG_PATH.exists():
        log.info("No config.yml — skipping plugin sync")
        return

    raw = yaml.safe_load(CONFIG_PATH.read_text())
    config = raw if isinstance(raw, dict) else {}
    plugin_config = config.get("plugins", {})
    if not isinstance(plugin_config, dict):
        log.warning("Invalid plugins config (expected dict, got %s), skipping", type(plugin_config).__name__)
        return
    if not plugin_config:
        log.info("No plugins section in config — skipping sync")
        return

    # Ensure marketplaces are registered
    desired_marketplaces = plugin_config.get("marketplaces", [])
    current_marketplaces = get_marketplaces()

    for source in desired_marketplaces:
        # source is "owner/repo" — marketplace name is the repo name
        name = source.split("/")[-1] if "/" in source else source
        if name in current_marketplaces:
            log.info("Marketplace %s already registered", name)
        else:
            log.info("Adding marketplace %s...", source)
            rc, out = run(["claude", "plugins", "marketplace", "add", source], timeout=120)
            if rc == 0:
                log.info("Added marketplace %s", name)
            else:
                log.error("Failed to add marketplace %s: %s", source, out)

    # Update all marketplaces (git pull)
    log.info("Updating marketplaces...")
    rc, out = run(["claude", "plugins", "marketplace", "update"], timeout=120)
    if rc != 0:
        log.warning("Marketplace update failed (non-fatal): %s", out)

    # Install missing plugins
    desired_plugins = set(plugin_config.get("install", []))
    current_plugins = get_installed()

    for plugin in desired_plugins:
        if plugin in current_plugins:
            log.info("Plugin %s already installed", plugin)
        else:
            log.info("Installing plugin %s...", plugin)
            rc, out = run(["claude", "plugins", "install", plugin], timeout=60)
            if rc == 0:
                log.info("Installed %s", plugin)
            else:
                log.error("Failed to install %s: %s", plugin, out)

    # Sync Gemini skills (separate ecosystem)
    gemini_skills = plugin_config.get("gemini_skills", [])
    if gemini_skills:
        installed_gemini = set()
        rc, out = run(["gemini", "skills", "list"], timeout=15)
        if rc == 0:
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith(("─", "Name", "No ")):
                    installed_gemini.add(line.split()[0])

        for source in gemini_skills:
            name = source.rstrip("/").split("/")[-1]
            if name in installed_gemini:
                log.info("Gemini skill %s already installed", name)
            else:
                log.info("Installing Gemini skill %s...", source)
                rc, out = run(["gemini", "skills", "install", source], timeout=120)
                if rc == 0:
                    log.info("Installed Gemini skill %s", name)
                else:
                    log.warning("Failed to install Gemini skill %s (non-fatal): %s", source, out[:200])

    log.info("Plugin sync complete (%d Claude plugins)", len(get_installed()))


if __name__ == "__main__":
    try:
        sync()
    except (subprocess.SubprocessError, yaml.YAMLError, OSError, KeyError, AttributeError, RuntimeError) as _:
        log.exception("Plugin sync failed (non-fatal, continuing)")
        # Non-fatal — container should still start even if plugin sync fails
