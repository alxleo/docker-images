# hadolint ignore=DL3029
FROM --platform=linux/arm64 semaphoreui/semaphore@sha256:b321b08f9f39a1dbf2d38b577d53aafa0079e528f7c0f47fecc64af2a077fea0
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

USER root
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
# Tools needed by homelab Ansible playbooks running in Semaphore:
#   bind-tools (dig)  — DNS verification in connectivity-test.sh
#   curl              — HTTP checks in connectivity-test.sh, Pi-hole API
#   jq                — JSON parsing in connectivity-test.sh, pihole push
#   rsync             — pihole config push, deploy rsync mode
#   age               — SOPS age-key decryption (sops shells out to age)
#   just              — task runner used by homelab justfiles
#   uv                — Python package manager for ansible dependencies
#   tailscale         — mesh VPN client for cross-network connectivity checks
#   docker-cli        — Docker management (needs socket mount for local use)
RUN apk upgrade --no-cache && \
    apk add --no-cache bind-tools curl jq rsync age just uv tailscale docker-cli && \
    wget -q https://github.com/getsops/sops/releases/download/v3.12.1/sops-v3.12.1.linux.arm64 -O /usr/local/bin/sops && \
    echo "c7904d07bf1fb3ffdc329b0103ce70ff6a884aa7af7931427402bea0c09cc522  /usr/local/bin/sops" | sha256sum -c && \
    chmod +x /usr/local/bin/sops
USER semaphore
