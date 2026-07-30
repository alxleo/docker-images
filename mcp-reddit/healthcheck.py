#!/usr/bin/env python3
"""Check the native MCP endpoint with a real initialize request."""

from __future__ import annotations

import json
import os
import urllib.request

payload = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "docker-healthcheck", "version": "1"},
        },
    }
).encode()
request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ.get('MCP_PORT', '8080')}/mcp",
    data=payload,
    headers={
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request, timeout=4) as response:
    result = json.load(response).get("result", {})
if not isinstance(result.get("capabilities"), dict):
    raise SystemExit("MCP initialize returned no capabilities")
