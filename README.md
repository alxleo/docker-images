# docker-images

Pre-built Docker images for homelab services where upstream images are broken, stale, or missing needed plugins.

## Images

| Image | Why | Remove when |
|-------|-----|-------------|
| `ghcr.io/alxleo/caddy-cloudflare:2.10` | Caddy + Cloudflare DNS plugin for ACME DNS-01 challenges | Never (plugin isn't in upstream Caddy) |
| `ghcr.io/alxleo/cadvisor:v0.56.2` | cAdvisor built from source — upstream stuck at v0.53.0 which crashes with Docker 29+ | ghcr.io publishes v0.57+ |

## How it works

GitHub Actions builds and pushes images to ghcr.io on push to `main`. Images are public — no auth needed to pull.

Manual trigger: Actions tab → Build Custom Images → Run workflow.
