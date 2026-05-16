# Upstream: sigbit/mcp-auth-proxy v2.9.1
#
# Final stage uses Alpine (not distroless/static) because the homelab compose
# pattern wraps the entrypoint in /bin/sh -c to materialize the Postgres DSN
# from Docker secrets at startup (see alxleo/homelab issue #401). Distroless
# has no shell. ~5MB layer increase over distroless/static.
#
# Runs as root (no USER directive). The homelab compose mounts Docker secrets
# with mode 0640 root:<host-group>; any non-root UID inside the container
# fails to read them. The container's effective security comes from
# cap_drop:ALL + read-only root + no direct network exposure (proxied behind
# Caddy), not from a non-root USER. Previous attempts to run non-root
# (USER 1000 in builds after v2.5.3-build.5, USER 65532 in #153) both
# crash-looped on secret reads. See alxleo/homelab#317 + #401 for incidents.

FROM ghcr.io/alxleo/base-images/golang:1.25-bookworm AS builder

ARG MCP_AUTH_PROXY_VERSION=v2.9.1

WORKDIR /src
RUN git clone --branch ${MCP_AUTH_PROXY_VERSION} --depth 1 https://github.com/sigbit/mcp-auth-proxy.git .

RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/local/bin/mcp-auth-proxy .

# conftest:exempt=healthcheck_required -- proxied behind caddy
# conftest:exempt=user_required -- must run as root to read mode-0640 Docker secrets (see header)
FROM ghcr.io/alxleo/base-images/alpine:3.23
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# ca-certificates: TLS bundle for OAuth IDP requests
# curl: required by the homelab compose healthcheck (services/auth-proxy.yml)
RUN apk add --no-cache ca-certificates curl

COPY --from=builder /usr/local/bin/mcp-auth-proxy /usr/local/bin/mcp-auth-proxy

RUN mkdir -p /data
ENV DATA_PATH=/data

# No USER directive — runs as root. See header for the secret-read constraint.

ENTRYPOINT ["/usr/local/bin/mcp-auth-proxy"]
