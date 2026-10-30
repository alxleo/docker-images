"""Check the proxy's effective TLS stores and package imports in the built image."""

import hashlib
import ssl
from importlib.metadata import version

import aiohttp
import certifi
import jwt
import pypdf
from opentelemetry.sdk.trace import TracerProvider
from litellm.proxy.management_endpoints.model_access_group_management_endpoints import (
    _access_group_info_for_deployments,
)

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
assert version("litellm") == "1.106.2"
print("Proxy dependencies import successfully")



groups = _access_group_info_for_deployments(
    [
        {"model_name": "haiku", "model_info": {"id": "config", "access_groups": ["daily", "monthly"]}},
        {"model_name": "sonnet", "model_info": {"id": "database", "access_groups": ["daily", "monthly"]}},
        {"model_name": "sonnet", "model_info": {"id": "database", "access_groups": ["daily", "monthly"]}},
        {"model_name": "haiku", "model_info": {"id": "replica", "access_groups": ["daily"]}},
        {"model_name": "subscription", "model_info": {"id": "quota-only"}},
    ]
)
assert set(groups) == {"daily", "monthly"}
assert groups["daily"].model_names == ["haiku", "sonnet"]
assert groups["daily"].deployment_count == 3
assert groups["monthly"].deployment_count == 2
assert _access_group_info_for_deployments([]) == {}
print("Configuration groups and database replicas share correctly deduplicated budgets")


for metadata in (None, "not-json", "[]"):
    assert _access_group_info_for_deployments(
        [{"model_name": "unrelated", "model_info": metadata}]
    ) == {}
assert _access_group_info_for_deployments([{"model_name": "unrelated"}]) == {}
