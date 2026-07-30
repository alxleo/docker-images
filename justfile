set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Validate discovery, manifests, unit contracts, and repository policies.
check:
    bash scripts/discover-images.sh | jq -e 'length > 0' >/dev/null
    uv run --with pytest --with pyyaml --with requests -- \
        pytest test/test_manifests.py test/test_entrypoint.py \
        test/test_custom_images.py::TestImageReferenceResolution \
        test/test_mcp_contract.py -q
    conftest verify -p policy/
    conftest test --parser dockerfile -p policy/ -- */Dockerfile mcp/Dockerfile.*
    conftest test --parser yaml -p policy/ -- test/docker-compose*.yml examples/docker-compose.yml

# Build one custom or shared MCP image locally and run its configured tests.
test-image image:
    bash scripts/test-image.sh "{{ image }}"
