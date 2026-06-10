# Upstream: sigbit/mcp-auth-proxy v2.10.2
#
# Alpine final stage so shell-based entrypoint wrappers work (materializing
# env from Docker secret files, etc.). ~5MB over distroless/static.
#
# Runs as root. Compose short-syntax mounts secrets at mode 0640 host-uid-
# owned; a non-root UID inside the container can't read them. Effective
# security here is cap_drop:ALL + read_only + reverse-proxy isolation. If
# you need non-root, use Compose long-syntax with `uid:` to chown secrets
# on materialization.

FROM ghcr.io/alxleo/base-images/golang:1.25-bookworm AS builder

# CVE-2026-33816 (pgx v5.7.6 → v5.9.2 fixed in upstream v2.10.1): bump to v2.10.2 (latest stable).
ARG MCP_AUTH_PROXY_VERSION=v2.10.2

WORKDIR /src
RUN git clone --branch ${MCP_AUTH_PROXY_VERSION} --depth 1 https://github.com/sigbit/mcp-auth-proxy.git .

# v2.10.2 requires go 1.26.2; GOTOOLCHAIN=auto lets the go 1.25 image download it.
ENV GOTOOLCHAIN=auto
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/local/bin/mcp-auth-proxy .

# conftest:exempt=healthcheck_required -- proxied behind a reverse proxy
# conftest:exempt=user_required -- runs as root to read default-mode Compose secrets (see header)
FROM ghcr.io/alxleo/base-images/alpine:3.23
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# ca-certificates: TLS bundle for OAuth IDP requests
# curl: typical healthcheck dependency
RUN apk add --no-cache ca-certificates curl

COPY --from=builder /usr/local/bin/mcp-auth-proxy /usr/local/bin/mcp-auth-proxy

RUN mkdir -p /data
ENV DATA_PATH=/data

ENTRYPOINT ["/usr/local/bin/mcp-auth-proxy"]
