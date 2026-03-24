# Custom Caddy with Cloudflare DNS + caddy-docker-proxy plugins.
# - Cloudflare DNS: ACME DNS-01 challenges for Let's Encrypt wildcard certs
# - caddy-docker-proxy: label-based routing from Docker container metadata
#
# Remove when: never (neither plugin is in upstream Caddy)

FROM caddy:2.11-builder AS builder
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/lucaslorentz/caddy-docker-proxy/v2

FROM caddy:2.11
RUN apk --no-cache upgrade
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
