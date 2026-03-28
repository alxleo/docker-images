# Custom Caddy with Cloudflare DNS + caddy-docker-proxy plugins.
# - Cloudflare DNS: ACME DNS-01 challenges for Let's Encrypt wildcard certs
# - caddy-docker-proxy: label-based routing from Docker container metadata
#
# Remove when: never (neither plugin is in upstream Caddy)

FROM ghcr.io/alxleo/base-images/caddy:2.11-builder AS builder
RUN echo "cache-bust: 2026-03-28" && xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/lucaslorentz/caddy-docker-proxy/v2

FROM ghcr.io/alxleo/base-images/caddy:2.11
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
RUN apk --no-cache upgrade
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
