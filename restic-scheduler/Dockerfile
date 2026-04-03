# Restic backup scheduler — restic + rclone + supercronic in one container.
#
# Replaces resticker's three-container pattern (one per cron type) with a
# single container running multiple cron jobs via supercronic.
#
# Base: mazzolino/restic (restic + rclone + backup/prune/check scripts)
# Added: supercronic (Go cron daemon, preserves env vars, logs to stdout)
#
# Usage: mount a crontab at /etc/supercronic/crontab or set BACKUP_CRON,
# PRUNE_CRON, CHECK_CRON env vars (entrypoint generates the crontab).
#
# Remove when: never — supercronic is always needed on top of resticker

ARG RESTICKER_VERSION=1.8.2
ARG SUPERCRONIC_VERSION=0.2.44

# Runs as root: supercronic PID 1 + Docker socket + backup volume writes
# trivy:ignore:DS-0002
# trivy:ignore:DS-0026 -- cron runner, no HTTP service port
FROM mazzolino/restic:${RESTICKER_VERSION}
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ARG SUPERCRONIC_VERSION
ARG TARGETARCH

# Install supercronic — single Go binary, no dependencies
RUN set -eux; \
    ARCH="${TARGETARCH}"; \
    case "${ARCH}" in \
      amd64) ARCH_SUFFIX="linux-amd64" ;; \
      arm64) ARCH_SUFFIX="linux-arm64" ;; \
      *) echo "Unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac; \
    wget -qO /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-${ARCH_SUFFIX}"; \
    chmod +x /usr/local/bin/supercronic

COPY entrypoint.sh /usr/local/bin/scheduler-entrypoint.sh
RUN chmod +x /usr/local/bin/scheduler-entrypoint.sh

RUN mkdir -p /etc/supercronic

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/scheduler-entrypoint.sh"]
