"""Exercise the installed REST route and MCP callbacks without a model or network."""
import asyncio
import json
import os

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'

from fastapi import HTTPException
from starlette.requests import Request
from litellm.proxy import proxy_server
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy._experimental.mcp_server import rest_endpoints
from litellm.proxy._experimental.mcp_server.operations import call_mcp_tool
from litellm.proxy._experimental.mcp_server.mcp_server_manager import global_mcp_server_manager as manager
from litellm.proxy._experimental.mcp_server.tool_registry import global_mcp_tool_registry as registry
from litellm.types.mcp_server.mcp_server_manager import MCPServer


async def main():
    proxy_server.proxy_logging_obj._init_litellm_callbacks()
    manager.registry['fixture'] = MCPServer(
        server_id='fixture', name='fixture', server_name='fixture',
        transport='http', spec_path='/offline.yaml', allowed_tools=['echo'],
    )
    entered = asyncio.Queue()
    release = asyncio.Event()

    async def echo(hold=False, fail=False):
        if hold:
            await entered.put(True)
            await release.wait()
        if fail:
            raise ValueError('Fixture tool failure')
        return 'fixture-result'

    registry.register_tool('fixture-echo', 'Read fixture', {
        'type': 'object', 'properties': {'hold': {'type': 'boolean'}, 'fail': {'type': 'boolean'}},
    }, echo, server_id='fixture')

    def auth(key, rpm=20, virtual=False):
        return UserAPIKeyAuth(
            api_key=key, max_parallel_requests=2, rpm_limit=rpm,
            object_permission={
                'object_permission_id': 'fixture', 'mcp_servers': ['fixture'], 'mcp_tool_search_enabled': virtual,
            },
        )

    async def invoke(caller, arguments=None, virtual=False):
        request = Request({
            'type': 'http', 'method': 'POST', 'scheme': 'https',
            'path': '/mcp-rest/tools/call', 'root_path': '', 'query_string': b'',
            'headers': [], 'server': ('offline.test', 443), 'client': ('127.0.0.1', 12345),
        })
        payload = {'server_id': 'fixture', 'name': 'fixture-echo', 'arguments': arguments or {}}
        if virtual:
            payload = {'name': 'mcp_tool_call', 'arguments': {'tool_name': 'fixture-echo', 'arguments': arguments or {}}}
        request._body = json.dumps(payload).encode()
        return await asyncio.create_task(rest_endpoints.call_tool_rest_api(request, user_api_key_dict=caller))

    for virtual in (False, True):
        caller = auth(f'offline-rest-sequential-{virtual}', virtual=virtual)
        for fail in (False, True, False, False):
            result = await invoke(caller, {'fail': fail}, virtual=virtual)
            assert result.is_error == fail, result
    print('Direct and virtual REST calls passed at parallel=2, including tool-error release')

    caller = auth('offline-rest-concurrent')
    held = [asyncio.create_task(invoke(caller, {'hold': True})) for _ in range(2)]
    await entered.get()
    await entered.get()
    try:
        await invoke(caller)
    except HTTPException as exc:
        assert exc.status_code == 429, exc
    else:
        raise AssertionError('Third concurrent REST call bypassed admission')
    release.set()
    assert all(not result.is_error for result in await asyncio.gather(*held))
    assert not (await invoke(caller)).is_error
    print('Third concurrent REST call rejected; capacity recovered after completion')

    caller = auth('offline-rest-rpm', rpm=3)
    for _ in range(3):
        assert not (await invoke(caller)).is_error
    try:
        await invoke(caller)
    except HTTPException as exc:
        assert exc.status_code == 429, exc
    else:
        raise AssertionError('Completion incorrectly refunded the RPM charge')
    print('REST RPM remains charged after completion')

    result = await call_mcp_tool(
        name='fixture-echo', arguments={}, mcp_servers=['fixture'], user_api_key_auth=auth('offline-native-control'),
    )
    assert not result.is_error and result.content[0].text == 'fixture-result', result
    print('Native MCP tool call remains functional')


asyncio.run(main())
