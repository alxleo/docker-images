#!/usr/bin/env python3
"""Check the native MCP endpoint with a real initialize request."""

from __future__ import annotations

import http.client
import json
import os

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
connection = http.client.HTTPConnection(
    "127.0.0.1", port=int(os.environ.get("MCP_PORT", "8080")), timeout=4
)
connection.request(
    "POST",
    "/mcp",
    body=payload,
    headers={
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    },
)
with connection.getresponse() as response:
    result = json.load(response).get("result", {})
if not isinstance(result.get("capabilities"), dict):
    raise SystemExit("MCP initialize returned no capabilities")
