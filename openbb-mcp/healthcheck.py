#!/usr/bin/env python3
"""Probe the native OpenBB Streamable HTTP handshake."""

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
            "clientInfo": {"name": "openbb-image-healthcheck", "version": "1"},
        },
    }
).encode()
connection = http.client.HTTPConnection(
    "127.0.0.1", int(os.environ.get("MCP_PORT", "8080")), timeout=6
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
session_id = None
with connection.getresponse() as response:
    session_id = response.getheader("Mcp-Session-Id")
    body = response.read().decode("utf-8")
if response.status // 100 != 2:
    raise SystemExit(f"MCP initialize failed with HTTP {response.status}: {body[:200]}")
if '"capabilities"' not in body:
    raise SystemExit("MCP initialize returned no capabilities")
if session_id:
    close_connection = http.client.HTTPConnection(
        "127.0.0.1", int(os.environ.get("MCP_PORT", "8080")), timeout=4
    )
    close_connection.request("DELETE", "/mcp", headers={"Mcp-Session-Id": session_id})
    with close_connection.getresponse() as response:
        response.read()
        if response.status // 100 != 2 and response.status != 404:
            raise SystemExit(f"MCP session cleanup failed with HTTP {response.status}")
    close_connection.close()
