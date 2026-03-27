# Custom Caddy with Cloudflare DNS, caddy-docker-proxy, and caddy-tailscale plugins.
# - Cloudflare DNS: ACME DNS-01 challenges for Let's Encrypt wildcard certs
# - caddy-docker-proxy: label-based routing from Docker container metadata
# - caddy-tailscale: embedded Tailscale nodes for per-service .ts.net HTTPS access
#
# Remove when: never (none of these plugins are in upstream Caddy)

FROM ghcr.io/alxleo/base-images/caddy:2.11-builder AS builder
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/lucaslorentz/caddy-docker-proxy/v2 \
    --with github.com/tailscale/caddy-tailscale

FROM ghcr.io/alxleo/base-images/caddy:2.11
RUN apk --no-cache upgrade
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
