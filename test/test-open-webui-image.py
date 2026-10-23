"""Check trust stores and the preserved Open WebUI application in its image."""

import hashlib
import ssl

import certifi
from fastapi.testclient import TestClient
from open_webui.main import app
from pip._vendor import certifi as pip_certifi

AFFECTED_ROOT = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"
for name, path in (("system", None), ("certifi", certifi.where()), ("pip", pip_certifi.where())):
    roots = ssl.create_default_context(cafile=path).get_ca_certs(binary_form=True)
    assert roots and AFFECTED_ROOT not in {hashlib.sha256(root).hexdigest() for root in roots}, name
    print(f"{name}: {len(roots)} trusted roots; affected root absent")

with TestClient(app) as client:
    response = client.get("/health")
    assert response.status_code == 200 and response.json()["status"] is True
    response = client.get("/api/version")
    assert response.status_code == 200 and response.json()["version"] == "0.11.4"
print("Native application lifespan, health and version passed")
