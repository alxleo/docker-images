# Custom Caddy with Cloudflare DNS plugin for ACME DNS-01 challenges.
# Enables automatic HTTPS with Let's Encrypt wildcard certs on LAN
# (no port 80 challenge needed — DNS validation via Cloudflare API).
#
# Remove when: never (Cloudflare DNS plugin isn't in upstream Caddy)

FROM caddy:2.11-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.11
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
