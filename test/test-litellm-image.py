"""Check the proxy's effective TLS stores and package imports in the built image."""

import hashlib
import ssl
from importlib.metadata import version

import aiohttp
import certifi
import jwt
import pypdf
from litellm.cost_calculator import response_cost_calculator
from litellm.litellm_core_utils.core_helpers import process_response_headers
from litellm.llms.openai.chat.gpt_transformation import OpenAIGPTConfig
from litellm.proxy.auth.model_checks import get_known_models_from_wildcard
from litellm.types.llms.openai import ResponsesAPIResponse
from litellm.types.router import LiteLLM_Params
from opentelemetry.sdk.trace import TracerProvider

import litellm

COMPROMISED_ROOT = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"

for name, context in (
    ("system", ssl.create_default_context()),
    ("certifi", ssl.create_default_context(cafile=certifi.where())),
):
    roots = context.get_ca_certs(binary_form=True)
    assert len(roots) > 100, (name, len(roots))
    assert COMPROMISED_ROOT not in {hashlib.sha256(cert).hexdigest() for cert in roots}, name
    print(f"{name}: {len(roots)} trusted roots; compromised emSign G3 root absent")

assert aiohttp.ClientSession
assert jwt.decode
assert pypdf.PdfReader
assert TracerProvider
print(f"LiteLLM {version('litellm')}: proxy dependencies import successfully")


# Exercise the installed provider catalogue and wildcard expansion offline.
litellm.check_provider_endpoint = False
litellm.models_by_provider["litellm_proxy"] = [
    "litellm_proxy/local/chat",
    "litellm_proxy/local/local/repeated",
    "litellm_proxy/publisher/chat",
    "ollama/gemma3:1b",
    "meta-llama/Llama-3-8B",
]
assert get_known_models_from_wildcard(
    "local/*", LiteLLM_Params(model="litellm_proxy/local/*")
) == [
    "local/chat",
    "local/local/repeated",
    "local/publisher/chat",
    "local/gemma3:1b",
    "local/meta-llama/Llama-3-8B",
]
print("Wildcard discovery preserves callable gateway ids and publisher paths")

# The same provider id needs different public names for these two templates.
litellm.models_by_provider["litellm_proxy"] = ["litellm_proxy/local/chat"]
for upstream_template, expected_name in (
    ("litellm_proxy/local/*", "local/chat"),
    ("litellm_proxy/*", "local/local/chat"),
):
    params = LiteLLM_Params(model=upstream_template, api_key="offline")
    names = get_known_models_from_wildcard("local/*", params)
    assert names == [expected_name]
    router = litellm.Router(model_list=[{
        "model_name": "local/*",
        "litellm_params": params.model_dump(exclude_none=True),
    }])
    resolved = router.get_available_deployment(model=names[0], messages=[{"role": "user", "content": "offline"}])
    assert resolved["litellm_params"]["model"] == "litellm_proxy/local/chat"
print("Both wildcard templates list names that route to the published upstream id")

for api_base, expected_url in (
    (None, "https://api.openai.com/v1/models"),
    ("https://example.test", "https://example.test/v1/models"),
    ("https://example.test/v1/", "https://example.test/v1/models"),
    ("https://example.test/gateway", "https://example.test/gateway/v1/models"),
    ("https://example.test/gateway/v1", "https://example.test/gateway/v1/models"),
    ("https://example.test/v1/chat/completions", "https://example.test/v1/models"),
    ("https://example.test/gateway/v1/chat/completions/", "https://example.test/gateway/v1/models"),
    ("https://example.test/v1/completions", "https://example.test/v1/models"),
    ("https://example.test/gateway/completions/chat/completions", "https://example.test/gateway/completions/v1/models"),
    ("http://[::1]:4000/gateway/", "http://[::1]:4000/gateway/v1/models"),
    ("https://example.test/a%2Fb", "https://example.test/a%2Fb/v1/models"),
    ("https://user:pass@example.test/gateway?token=discard#fragment", "https://example.test/gateway/v1/models"),
):
    assert OpenAIGPTConfig._model_list_url(api_base) == expected_url
print("Provider model discovery preserves configured subpaths without duplicate API versions")


# An intermediary's notional receipt cannot replace server-owned token pricing.

for receipt, call_type, base_model in (
    (litellm.ModelResponse(model="subscription/gpt-6.1-sol", usage={
        "prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000,
    }), "acompletion", "openai/gpt-6.1-sol"),
    (ResponsesAPIResponse(id="offline", created_at=0, model="subscription/gpt-6.1-sol", output=[], usage={
        "input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000,
    }), "aresponses", "openai/gpt-6.1-sol"),
    (litellm.ImageResponse(created=0, data=[{"b64_json": "offline"}], usage={
        "input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000,
        "input_tokens_details": {"text_tokens": 1000, "image_tokens": 0},
    }), "aimage_generation", "openai/gpt-image-2"),
):
    params = {"size": "1024x1024", "quality": "low"} if "image" in call_type else {}
    expected = response_cost_calculator(
        response_object=receipt, model=base_model, base_model=base_model,
        custom_llm_provider="openai", call_type=call_type, optional_params=params,
    )
    assert expected > 0
    for cost in ("0", "123"):
        receipt._hidden_params["additional_headers"] = process_response_headers({"x-litellm-response-cost": cost})
        assert response_cost_calculator(
            response_object=receipt, model=base_model, base_model=base_model,
            custom_llm_provider="openai", call_type=call_type, optional_params=params,
        ) == expected
        assert response_cost_calculator(
            response_object=receipt, model=base_model, custom_llm_provider="openai",
            call_type=call_type, optional_params=params,
        ) == float(cost)
print("Configured token pricing survives zero or inflated upstream receipts for chat, Responses and images")


async def check_mcp_rest_accounting():
    import asyncio
    import json

    from fastapi import HTTPException
    from starlette.requests import Request

    from litellm.proxy import proxy_server
    from litellm.proxy._experimental.mcp_server import rest_endpoints
    from litellm.proxy._experimental.mcp_server.mcp_server_manager import global_mcp_server_manager as manager
    from litellm.proxy._experimental.mcp_server.operations import call_mcp_tool
    from litellm.proxy._experimental.mcp_server.tool_registry import global_mcp_tool_registry as registry
    from litellm.proxy._types import UserAPIKeyAuth
    from litellm.types.mcp_server.mcp_server_manager import MCPServer

    proxy_server.proxy_logging_obj._init_litellm_callbacks()
    manager.registry['accounting'] = MCPServer(
        server_id='accounting', name='accounting', server_name='accounting',
        transport='http', spec_path='/offline.yaml', allowed_tools=['read', 'hold', 'fail'],
    )
    started, finish = asyncio.Event(), asyncio.Event()

    async def read():
        return 'offline book text'

    async def hold():
        started.set()
        await finish.wait()
        return 'offline book text'

    async def fail():
        raise HTTPException(status_code=422, detail='offline input rejected')

    for name, handler in [('read', read), ('hold', hold), ('fail', fail), ('blocked', read)]:
        registry.register_tool(f'accounting-{name}', name, {'type': 'object'}, handler, server_id='accounting')

    def key(label, rpm=20, servers=None):
        return UserAPIKeyAuth(
            api_key=f'offline-{label}', max_parallel_requests=1, rpm_limit=rpm,
            object_permission={'object_permission_id':label, 'mcp_servers': servers or ['accounting']},
        )

    async def rest(auth, name='read'):
        request = Request({
            'type':'http', 'method':'POST', 'scheme':'https', 'path':'/mcp-rest/tools/call',
            'root_path':'', 'query_string':b'', 'headers':[], 'server':('offline.test',443),
            'client':('127.0.0.1',12345),
        })
        request._body = json.dumps({'server_id':'accounting', 'name':f'accounting-{name}', 'arguments':{}}).encode()
        return await rest_endpoints.call_tool_rest_api(request, user_api_key_dict=auth)

    async def denied(awaitable, status):
        try:
            await asyncio.create_task(awaitable)
        except HTTPException as error:
            assert error.status_code == status, (status, error.status_code)
        else:
            raise AssertionError(f'Expected HTTP {status}')

    quota_key = key('quota', rpm=3)
    native = await asyncio.create_task(call_mcp_tool(
        name='accounting-read', arguments={}, mcp_servers=['accounting'], user_api_key_auth=quota_key,
    ))
    assert not native.is_error and native.content[0].text == 'offline book text'
    for _ in range(2):
        result = await asyncio.create_task(rest(quota_key))
        assert not result.is_error and result.content[0].text == 'offline book text'
    await denied(rest(quota_key), 429)
    print('MCP quota: native + two REST reads succeed at concurrency one; fourth call hits RPM three')

    parallel_key = key('parallel')
    active = asyncio.create_task(rest(parallel_key, 'hold'))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await denied(rest(parallel_key), 429)
    finally:
        finish.set()
        completed = await active
        assert not completed.is_error
    assert not (await asyncio.create_task(rest(parallel_key))).is_error
    print('MCP concurrency: overlapping read denied; the next read succeeds after completion')

    failed_key = key('failure')
    failed = await asyncio.create_task(rest(failed_key, 'fail'))
    assert failed.is_error
    assert not (await asyncio.create_task(rest(failed_key))).is_error
    await denied(rest(key('blocked'), 'blocked'), 403)
    await denied(rest(key('scope', servers=['another-server'])), 403)
    print('MCP failures: failed calls release their slot; tool and server denials remain HTTP 403')


import asyncio

asyncio.run(check_mcp_rest_accounting())
