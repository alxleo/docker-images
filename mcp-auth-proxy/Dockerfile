# Upstream: sigbit/mcp-auth-proxy v2.9.1
#
# Final stage uses Alpine (not distroless/static) because the homelab compose
# pattern wraps the entrypoint in /bin/sh -c to materialize the Postgres DSN
# from Docker secrets at startup (see alxleo/homelab issue #401). Distroless
# has no shell. ~5MB layer increase over distroless/static.

FROM ghcr.io/alxleo/base-images/golang:1.25-bookworm AS builder

ARG MCP_AUTH_PROXY_VERSION=v2.9.1

WORKDIR /src
RUN git clone --branch ${MCP_AUTH_PROXY_VERSION} --depth 1 https://github.com/sigbit/mcp-auth-proxy.git .

RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/local/bin/mcp-auth-proxy .

# conftest:exempt=healthcheck_required -- proxied behind caddy
FROM ghcr.io/alxleo/base-images/alpine:3.23
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

RUN apk add --no-cache ca-certificates

COPY --from=builder /usr/local/bin/mcp-auth-proxy /usr/local/bin/mcp-auth-proxy

# UID matches the previous distroless `nonroot` user (65532) so existing
# auth-proxy-data volume permissions carry over without a chown sweep.
RUN addgroup -g 65532 -S nonroot \
    && adduser -u 65532 -G nonroot -S -D -s /sbin/nologin nonroot \
    && mkdir -p /data \
    && chown 65532:65532 /data
ENV DATA_PATH=/data

USER 65532

ENTRYPOINT ["/usr/local/bin/mcp-auth-proxy"]
