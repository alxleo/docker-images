"""Check the proxy's effective TLS stores and package imports in the built image."""

import hashlib
import ssl
from importlib.metadata import version

import aiohttp
import certifi
import jwt
import pypdf
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
