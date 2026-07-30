#!/usr/bin/env python3
"""Capture and compare deterministic MCP tool contracts over Streamable HTTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-03-26"
LOCK_VERSION = 1


class ContractError(RuntimeError):
    """Raised when an MCP endpoint does not satisfy the contract protocol."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def normalize_tools(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce tools/list output to stable names and input-schema hashes."""
    normalized = []
    seen_names: set[str] = set()

    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ContractError("tools/list returned a tool without a non-empty name")
        if name in seen_names:
            raise ContractError(f"tools/list returned duplicate tool name: {name}")
        seen_names.add(name)

        input_schema = tool.get("inputSchema", {})
        if not isinstance(input_schema, dict):
            raise ContractError(f"{name}: inputSchema must be an object")
        schema_hash = hashlib.sha256(_canonical_json(input_schema).encode()).hexdigest()
        normalized.append(
            {
                "name": name,
                "input_schema_sha256": f"sha256:{schema_hash}",
            }
        )

    normalized.sort(key=lambda tool: tool["name"])
    return {"lock_version": LOCK_VERSION, "tools": normalized}


def _extract_json(content_type: str, body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8")
    candidates = []
    if "text/event-stream" in content_type:
        candidates.extend(
            line.removeprefix("data:").strip()
            for line in text.splitlines()
            if line.startswith("data:")
        )
    else:
        candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ContractError(f"MCP endpoint returned no JSON object: {text[:300]}")


class MCPClient:
    def __init__(self, url: str, timeout: float = 30) -> None:
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.request_id = 0

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["Mcp-Protocol-Version"] = self.protocol_version

        request = urllib.request.Request(
            self.url,
            data=_canonical_json(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if session_id := response.headers.get("Mcp-Session-Id"):
                    self.session_id = session_id
                body = response.read()
                if not body:
                    return None
                return _extract_json(response.headers.get_content_type(), body)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ContractError(
                f"MCP request failed with HTTP {error.code}: {body[:300]}"
            ) from error
        except urllib.error.URLError as error:
            raise ContractError(f"MCP request failed: {error.reason}") from error

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params,
            }
        )
        if response is None:
            raise ContractError(f"{method} returned an empty response")
        if "error" in response:
            raise ContractError(f"{method} failed: {_canonical_json(response['error'])}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise ContractError(f"{method} returned no result object")
        return result

    def initialize(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "docker-images-contract", "version": "1"},
            },
        )
        if not isinstance(result.get("capabilities"), dict):
            raise ContractError("initialize returned no capabilities object")
        negotiated_version = result.get("protocolVersion")
        if not isinstance(negotiated_version, str) or not negotiated_version:
            raise ContractError("initialize returned no protocolVersion")
        self.protocol_version = negotiated_version
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._request("tools/list", params)
            page = result.get("tools")
            if not isinstance(page, list) or not all(
                isinstance(tool, dict) for tool in page
            ):
                raise ContractError("tools/list returned no tools array")
            tools.extend(page)

            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ContractError("tools/list returned an invalid nextCursor")
            if next_cursor in seen_cursors:
                raise ContractError("tools/list repeated a pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor


def capture(url: str, timeout: float) -> dict[str, Any]:
    client = MCPClient(url, timeout)
    client.initialize()
    return normalize_tools(client.list_tools())


def compare_contracts(
    expected: dict[str, Any], actual: dict[str, Any]
) -> list[str]:
    if expected.get("lock_version") != LOCK_VERSION:
        return [f"unsupported expected lock_version: {expected.get('lock_version')}"]

    expected_tools = {tool["name"]: tool for tool in expected.get("tools", [])}
    actual_tools = {tool["name"]: tool for tool in actual.get("tools", [])}
    differences = []

    for name in sorted(expected_tools.keys() - actual_tools.keys()):
        differences.append(f"missing tool: {name}")
    for name in sorted(actual_tools.keys() - expected_tools.keys()):
        differences.append(f"unexpected tool: {name}")
    for name in sorted(expected_tools.keys() & actual_tools.keys()):
        expected_hash = expected_tools[name].get("input_schema_sha256")
        actual_hash = actual_tools[name].get("input_schema_sha256")
        if expected_hash != actual_hash:
            differences.append(
                f"schema changed: {name} ({expected_hash} -> {actual_hash})"
            )
    return differences


def _write_json(path: Path, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path == Path("-"):
        sys.stdout.write(rendered)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Streamable HTTP MCP endpoint")
    parser.add_argument("--timeout", type=float, default=30)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", type=Path, metavar="PATH")
    mode.add_argument("--verify", type=Path, metavar="PATH")
    args = parser.parse_args()

    try:
        actual = capture(args.url, args.timeout)
        if args.capture is not None:
            _write_json(args.capture, actual)
            return 0

        expected = json.loads(args.verify.read_text())
        differences = compare_contracts(expected, actual)
        if differences:
            print("MCP contract mismatch:", file=sys.stderr)
            for difference in differences:
                print(f"  - {difference}", file=sys.stderr)
            return 1
        print(f"PASS: MCP contract matches ({len(actual['tools'])} tools)")
        return 0
    except (ContractError, json.JSONDecodeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
