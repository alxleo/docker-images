"""Readiness for the native MCP service."""

import http.client

connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=4)
connection.request("GET", "/ping")
with connection.getresponse() as response:
    if response.status != 200 or response.read() != b"pong":
        raise SystemExit("Search MCP is not ready")
