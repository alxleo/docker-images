#!/usr/bin/env python3
"""Healthcheck for either the FinRobot API or MCP command."""

from __future__ import annotations

import http.client
import json
import os


mode = os.environ.get("FINROBOT_MODE")
if mode is None:
    # Docker HEALTHCHECK runs outside the entrypoint shell. Probe the API
    # first so the same image works for both `api` and `mcp` commands.
    try:
        probe = http.client.HTTPConnection("127.0.0.1", int(os.environ.get("FINROBOT_API_PORT", "8000")), timeout=1)
        probe.request("GET", "/health")
        mode = "api" if probe.getresponse().status // 100 == 2 else "mcp"
        probe.close()
    except OSError:
        mode = "mcp"
if mode == "mcp":
    port = int(os.environ.get("FINROBOT_MCP_PORT", "8080"))
    path = "/mcp"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "finrobot-image-healthcheck", "version": "1"},
            },
        }
    ).encode()
else:
    port = int(os.environ.get("FINROBOT_API_PORT", "8000"))
    path = "/health"
    body = None

connection = http.client.HTTPConnection("127.0.0.1", port, timeout=6)
headers = {}
if body is not None:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
connection.request("POST" if body is not None else "GET", path, body=body, headers=headers)
session_id = None
with connection.getresponse() as response:
    session_id = response.getheader("Mcp-Session-Id")
    payload = response.read().decode("utf-8")
if response.status // 100 != 2:
    raise SystemExit(f"healthcheck failed with HTTP {response.status}: {payload[:200]}")
if mode == "mcp" and '"capabilities"' not in payload:
    raise SystemExit("MCP initialize returned no capabilities")
if session_id:
    close_connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    close_connection.request("DELETE", path, headers={"Mcp-Session-Id": session_id})
    with close_connection.getresponse() as response:
        response.read()
        if response.status // 100 != 2 and response.status != 404:
            raise SystemExit(f"MCP session cleanup failed with HTTP {response.status}")
    close_connection.close()
