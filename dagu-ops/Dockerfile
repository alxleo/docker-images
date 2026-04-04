# Dagu operations control plane — Dagu + restic + rclone + Docker CLI.
#
# Single container for all scheduled homelab operations: backups, health
# checks, drift detection, cleanup. Tools baked in once, available to
# all DAG workflows.
#
# Base: Ubuntu 24.04 (dagu-org stopped publishing Docker images to GHCR)
# Added: dagu binary, restic, rclone, openssh-client, docker-cli, curl, jq
#
# Remove when: never — ops tooling layer is always needed on top of Dagu

# conftest:exempt=user_required -- Docker socket + backup volume writes
FROM ubuntu:24.04
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ARG DAGU_VERSION=2.3.11
# ARG names avoid RCLONE_ prefix — rclone interprets RCLONE_* env vars as CLI flags
ARG RESTIC_VERSION=0.18.1
ARG RCLONE_DL_VERSION=1.73.3
ARG DOCKER_CLI_VERSION=27.5.1
ARG TARGETARCH

# Install system packages (jq was included in the old dagu base image)
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-client \
      curl \
      ca-certificates \
      bzip2 \
      unzip \
      jq \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install Dagu (binary release — upstream stopped publishing Docker images)
RUN set -eux; \
    curl -fsSL "https://github.com/dagucloud/dagu/releases/download/v${DAGU_VERSION}/dagu_${DAGU_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar xz -C /usr/local/bin dagu; \
    dagu version

# Install Docker CLI (official static binary — no Docker daemon)
RUN set -eux; \
    curl -fsSL "https://download.docker.com/linux/static/stable/$(uname -m)/docker-${DOCKER_CLI_VERSION}.tgz" \
      | tar xz --strip-components=1 -C /usr/local/bin docker/docker; \
    docker --version

# Install restic
RUN set -eux; \
    curl -fsSL "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_${TARGETARCH}.bz2" \
      | bunzip2 > /usr/local/bin/restic; \
    chmod +x /usr/local/bin/restic; \
    restic version

# Install rclone
RUN set -eux; \
    curl -fsSL "https://downloads.rclone.org/v${RCLONE_DL_VERSION}/rclone-v${RCLONE_DL_VERSION}-linux-${TARGETARCH}.zip" \
      -o /tmp/rclone.zip; \
    unzip -j /tmp/rclone.zip "*/rclone" -d /usr/local/bin/; \
    chmod +x /usr/local/bin/rclone; \
    rm /tmp/rclone.zip; \
    rclone version | head -1

COPY entrypoint.sh /usr/local/bin/dagu-ops-entrypoint.sh
RUN chmod +x /usr/local/bin/dagu-ops-entrypoint.sh

# Scripts directory for shared utilities (notify, etc.)
RUN mkdir -p /scripts

ENTRYPOINT ["/usr/local/bin/dagu-ops-entrypoint.sh"]
CMD ["dagu", "start-all"]
