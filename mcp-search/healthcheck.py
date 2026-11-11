"""Readiness for the native MCP service."""

import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8080/ping", timeout=4) as response:
    if response.status != 200 or response.read() != b"pong":
        raise SystemExit("Search MCP is not ready")
