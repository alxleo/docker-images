import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "mcp_contract", REPO_ROOT / "scripts" / "mcp-contract.py"
)
assert SPEC and SPEC.loader
mcp_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcp_contract)


def test_normalize_tools_is_order_and_key_order_independent():
    first = [
        {
            "name": "zeta",
            "description": "ignored",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string", "minLength": 1}},
            },
        },
        {"name": "alpha", "inputSchema": {"type": "object"}},
    ]
    second = [
        {"inputSchema": {"type": "object"}, "name": "alpha"},
        {
            "inputSchema": {
                "properties": {"query": {"minLength": 1, "type": "string"}},
                "type": "object",
            },
            "name": "zeta",
        },
    ]

    assert mcp_contract.normalize_tools(first) == mcp_contract.normalize_tools(second)
    assert [
        tool["name"] for tool in mcp_contract.normalize_tools(first)["tools"]
    ] == ["alpha", "zeta"]


def test_normalize_tools_rejects_duplicate_names():
    with pytest.raises(mcp_contract.ContractError, match="duplicate tool name"):
        mcp_contract.normalize_tools([{"name": "same"}, {"name": "same"}])


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:secret@example.test/mcp",
        "http://example.test/mcp#fragment",
    ],
)
def test_client_rejects_non_http_or_credential_bearing_urls(url):
    with pytest.raises(mcp_contract.ContractError):
        mcp_contract.MCPClient(url)


def test_compare_contracts_reports_added_removed_and_changed():
    expected = {
        "lock_version": 1,
        "tools": [
            {"name": "changed", "input_schema_sha256": "sha256:old"},
            {"name": "removed", "input_schema_sha256": "sha256:same"},
        ],
    }
    actual = {
        "lock_version": 1,
        "tools": [
            {"name": "added", "input_schema_sha256": "sha256:new"},
            {"name": "changed", "input_schema_sha256": "sha256:new"},
        ],
    }

    assert mcp_contract.compare_contracts(expected, actual) == [
        "missing tool: removed",
        "unexpected tool: added",
        "schema changed: changed (sha256:old -> sha256:new)",
    ]


def test_extract_json_accepts_plain_json_and_sse():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    encoded = json.dumps(payload).encode()

    assert mcp_contract._extract_json("application/json", encoded) == payload
    assert (
        mcp_contract._extract_json("text/event-stream", b"event: message\ndata: " + encoded)
        == payload
    )


def test_extract_json_skips_sse_notifications_before_response():
    response = {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}
    body = (
        b"data: "
        + json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
        ).encode()
        + b"\n\ndata: "
        + json.dumps(response).encode()
        + b"\n\n"
    )

    assert mcp_contract._extract_json("text/event-stream", body, expected_id=7) == response


def test_extract_json_joins_multiline_sse_data_fields():
    body = (
        b'event: message\ndata: {"jsonrpc":"2.0",\n'
        b'data: "id":7,"result":{"tools":[]}}\n\n'
    )

    assert mcp_contract._extract_json("text/event-stream", body, expected_id=7) == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"tools": []},
    }


def test_extract_json_selects_response_from_sse_batch():
    response = {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}
    batch = [
        {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
        response,
    ]

    assert (
        mcp_contract._extract_json(
            "text/event-stream",
            f"data: {json.dumps(batch)}\n\n".encode(),
            expected_id=7,
        )
        == response
    )


def test_post_stops_reading_open_sse_after_matching_response():
    response_payload = {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}

    class OpenSseResponse:
        status = 200

        def __init__(self):
            self.lines = iter(
                [f"data: {json.dumps(response_payload)}\n".encode(), b"\n"]
            )

        def getheader(self, name, default=None):
            if name == "Content-Type":
                return "text/event-stream"
            return default

        def readline(self):
            return next(self.lines)

        def read(self):
            raise AssertionError("open SSE response must not be read to EOF")

    class FakeConnection:
        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return OpenSseResponse()

        def close(self):
            pass

    client = mcp_contract.MCPClient("http://example.test/mcp")
    client.connection_class = lambda *args, **kwargs: FakeConnection()

    assert client._post(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    ) == response_payload


def test_list_tools_follows_pagination(monkeypatch):
    client = mcp_contract.MCPClient("http://example.test/mcp")
    pages = iter(
        [
            {"tools": [{"name": "first"}], "nextCursor": "page-2"},
            {"tools": [{"name": "second"}]},
        ]
    )
    requests = []

    def fake_request(method, params):
        requests.append((method, params))
        return next(pages)

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.list_tools() == [{"name": "first"}, {"name": "second"}]
    assert requests == [
        ("tools/list", {}),
        ("tools/list", {"cursor": "page-2"}),
    ]
