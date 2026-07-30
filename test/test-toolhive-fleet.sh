#!/usr/bin/env bash
# Live ToolHive oracle: exact package contract, MCPJam handshake, and tool denial.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FLEET="${ROOT}/mcp-fleet.json"
JQ_BIN="${JQ_BIN:-/usr/bin/jq}"
if [[ ! -x "$JQ_BIN" ]]; then
    JQ_BIN=$(command -v jq)
fi
TOOLHIVE_VERSION=$("$JQ_BIN" -er '.toolhive_version' "$FLEET")
MCPJAM_VERSION=$("$JQ_BIN" -er '.mcpjam_version' "$FLEET")
WORKLOAD="docker-images-toolhive-test-$$"
PORT="${TOOLHIVE_TEST_PORT:-19190}"
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/docker-images-toolhive.XXXXXX")
export XDG_CONFIG_HOME="${TEMP_DIR}/config"
export XDG_DATA_HOME="${TEMP_DIR}/data"
export XDG_STATE_HOME="${TEMP_DIR}/state"

cleanup() {
    if [[ -n "${THV_BIN:-}" && -x "${THV_BIN}" ]]; then
        "$THV_BIN" rm "$WORKLOAD" >/dev/null 2>&1 || true
    fi
    for container in "$WORKLOAD" "${WORKLOAD}-egress" "${WORKLOAD}-dns" "${WORKLOAD}-ingress"; do
        if docker container inspect "$container" >/dev/null 2>&1; then
            docker container rm --force "$container" >/dev/null
        fi
    done
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

resolve_docker_host() {
    local context host
    context=$(docker context show)
    host=$(docker context inspect "$context" --format '{{.Endpoints.docker.Host}}')
    if [[ "$host" == *".colima/"* ]]; then
        echo "ERROR: active Docker context resolves to Colima: ${host}" >&2
        exit 1
    fi
    export DOCKER_HOST="$host"
}

download_toolhive() {
    local os arch asset checksum_line
    os=$(uname -s | tr '[:upper:]' '[:lower:]')
    arch=$(uname -m)
    case "$arch" in
    arm64 | aarch64) arch=arm64 ;;
    x86_64 | amd64) arch=amd64 ;;
    *)
        echo "ERROR: unsupported architecture: ${arch}" >&2
        exit 1
        ;;
    esac
    asset="toolhive_${TOOLHIVE_VERSION}_${os}_${arch}.tar.gz"
    curl -fsSLo "${TEMP_DIR}/${asset}" \
        "https://github.com/stacklok/toolhive/releases/download/v${TOOLHIVE_VERSION}/${asset}"
    curl -fsSLo "${TEMP_DIR}/checksums.txt" \
        "https://github.com/stacklok/toolhive/releases/download/v${TOOLHIVE_VERSION}/toolhive_${TOOLHIVE_VERSION}_checksums.txt"
    checksum_line=$(awk -v asset="$asset" '$2 == asset {print}' "${TEMP_DIR}/checksums.txt")
    if [[ -z "$checksum_line" ]]; then
        echo "ERROR: ${asset} is absent from ToolHive checksums" >&2
        exit 1
    fi
    (cd "$TEMP_DIR" && printf '%s\n' "$checksum_line" | shasum -a 256 -c -)
    tar xzf "${TEMP_DIR}/${asset}" -C "$TEMP_DIR"
    THV_BIN="${TEMP_DIR}/thv"
}

wait_for_workload() {
    local status_file="${XDG_DATA_HOME}/toolhive/statuses/${WORKLOAD}.json"
    local status=""
    for _ in $(seq 1 60); do
        if [[ "$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' \
            -X POST "http://127.0.0.1:${PORT}/mcp" \
            -H 'Content-Type: application/json' \
            -H 'Accept: application/json, text/event-stream' \
            --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"fleet-readiness","version":"1.0"}}}' \
            2>/dev/null || true)" == 200 ]]; then
            return 0
        fi
        status=$("$JQ_BIN" -r '.status // empty' "$status_file" 2>/dev/null || true)
        case "$status" in
        error)
            "$JQ_BIN" . "$status_file" >&2
            return 1
            ;;
        *) ;;
        esac
        sleep 1
    done
    echo "ERROR: ${WORKLOAD} did not become ready (last status: ${status:-missing})" >&2
    return 1
}

run_hackernews() {
    local args=(
        --fleet "$FLEET" exec
        --server mcp-hackernews
        --thv-bin "$THV_BIN"
        --name "$WORKLOAD"
        --port "$PORT"
    )
    while (($#)); do
        args+=(--tool "$1")
        shift
    done
    python3 "${ROOT}/scripts/toolhive-fleet.py" "${args[@]}"
    wait_for_workload
}

resolve_docker_host
if [[ -z "${THV_BIN:-}" ]]; then
    download_toolhive
fi
if ! "$THV_BIN" version | grep -Fq "ToolHive v${TOOLHIVE_VERSION}"; then
    echo "ERROR: THV_BIN is not ToolHive v${TOOLHIVE_VERSION}" >&2
    exit 1
fi
"$THV_BIN" group create homelab >/dev/null

run_hackernews
python3 "${ROOT}/scripts/mcp-contract.py" \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --verify "${ROOT}/mcp-contracts/mcp-hackernews.json"
npx --yes "@mcpjam/cli@${MCPJAM_VERSION}" server probe \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --quiet --format json --no-telemetry |
    "$JQ_BIN" -e '.status == "ready"' >/dev/null

"$THV_BIN" rm "$WORKLOAD"
run_hackernews getTopStories getNewStories
FILTERED_LOCK="${TEMP_DIR}/filtered.json"
python3 "${ROOT}/scripts/mcp-contract.py" \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --capture "$FILTERED_LOCK"
"$JQ_BIN" -e '
    [.tools[].name] == ["getNewStories", "getTopStories"]
' "$FILTERED_LOCK" >/dev/null

HTTP_STATUS=$(curl -sS -o "${TEMP_DIR}/denied.json" -w '%{http_code}' \
    -X POST "http://127.0.0.1:${PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"getBestStories","arguments":{}}}')
test "$HTTP_STATUS" = 200
"$JQ_BIN" -e '
    .jsonrpc == "2.0" and .id == 99 and
    .error.code == -32602 and .error.message == "tool not found"
' "${TEMP_DIR}/denied.json" >/dev/null

"$THV_BIN" rm "$WORKLOAD"
WORKLOAD="${WORKLOAD}-arxiv"
PORT="${TOOLHIVE_ARXIV_TEST_PORT:-19191}"
export ARXIV_DATA_DIR="${TEMP_DIR}/arxiv-papers"
mkdir -p "$ARXIV_DATA_DIR"
python3 "${ROOT}/scripts/toolhive-fleet.py" \
    --fleet "$FLEET" exec \
    --server mcp-arxiv \
    --thv-bin "$THV_BIN" \
    --name "$WORKLOAD" \
    --port "$PORT"
wait_for_workload
python3 "${ROOT}/scripts/mcp-contract.py" \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --verify "${ROOT}/mcp-contracts/mcp-arxiv.json"
npx --yes "@mcpjam/cli@${MCPJAM_VERSION}" server probe \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --quiet --format json --no-telemetry |
    "$JQ_BIN" -e '.status == "ready"' >/dev/null

"$THV_BIN" rm "$WORKLOAD"
WORKLOAD="${WORKLOAD}-jina"
PORT="${TOOLHIVE_JINA_TEST_PORT:-19192}"
export TOOLHIVE_SECRET_JINA_AUTHORIZATION="Bearer test-not-a-real-key"
python3 "${ROOT}/scripts/toolhive-fleet.py" \
    --fleet "$FLEET" exec \
    --server mcp-jina \
    --thv-bin "$THV_BIN" \
    --name "$WORKLOAD" \
    --port "$PORT"
wait_for_workload
python3 "${ROOT}/scripts/mcp-contract.py" \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --verify "${ROOT}/mcp-contracts/mcp-jina.json"
npx --yes "@mcpjam/cli@${MCPJAM_VERSION}" server probe \
    --url "http://127.0.0.1:${PORT}/mcp" \
    --quiet --format json --no-telemetry |
    "$JQ_BIN" -e '.status == "ready"' >/dev/null
if rg -F "test-not-a-real-key" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" 2>/dev/null; then
    echo "ERROR: ToolHive persisted or logged a remote header secret value" >&2
    exit 1
fi
unset TOOLHIVE_SECRET_JINA_AUTHORIZATION

echo "PASS: ToolHive ${TOOLHIVE_VERSION} Node 26/Python 3.14/direct-remote contracts, MCPJam probes, and filtering"
