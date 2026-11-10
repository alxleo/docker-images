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
