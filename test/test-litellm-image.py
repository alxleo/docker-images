"""Check the proxy's effective TLS stores and package imports in the built image."""

import hashlib
import ssl
from importlib.metadata import version

import aiohttp
import certifi
import jwt
import pypdf
from litellm.llms.openai.chat.gpt_transformation import OpenAIGPTConfig
from litellm.proxy.auth.model_checks import get_known_models_from_wildcard
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
