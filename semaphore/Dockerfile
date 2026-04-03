# trivy:ignore:DS-0026 -- upstream manages health internally
FROM semaphoreui/semaphore@sha256:17678757e65621aaf27bffbfe8caa00fb85857d60124b49876a5326e3f3dfac9
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
ARG TARGETARCH
RUN apk upgrade --no-cache && \
    apk add --no-cache bind-tools curl jq rsync age just uv tailscale docker-cli && \
    case "$TARGETARCH" in \
      amd64) sops_sha256="cf3136d20a6004405c986a48e179c3c7a731f777fbf105a37bd5dac5c9047100" ;; \
      arm64) sops_sha256="c7904d07bf1fb3ffdc329b0103ce70ff6a884aa7af7931427402bea0c09cc522" ;; \
      "") echo "ERROR: TARGETARCH not set. Build with buildx or pass --build-arg TARGETARCH=amd64|arm64." >&2; exit 1 ;; \
      *) echo "ERROR: Unsupported TARGETARCH '$TARGETARCH'." >&2; exit 1 ;; \
    esac && \
    wget -q "https://github.com/getsops/sops/releases/download/v3.12.1/sops-v3.12.1.linux.${TARGETARCH}" -O /usr/local/bin/sops && \
    echo "${sops_sha256}  /usr/local/bin/sops" | sha256sum -c && \
    chmod +x /usr/local/bin/sops
USER semaphore
