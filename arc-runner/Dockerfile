# syntax=docker/dockerfile:1.7

FROM ghcr.io/actions/actions-runner:2.338.2@sha256:759a1d94a15b05941aba5196974ff43fe15b4cbba29b694b35cbc32a1166b232 AS runner
FROM ghcr.io/alxleo/gitea-ci-runner:latest@sha256:7fdf3164bd9f24dbb581bca69a98b3fa639e62f311ebab0179f23667d945e552

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Disposable ARC runner" \
      org.opencontainers.image.description="Released GitHub runner with the shared homelab CI toolchain"

USER 0:0
COPY --from=runner --chown=1001:1001 /home/runner /home/runner
RUN groupadd --gid 1001 runner && \
    useradd --uid 1001 --gid 1001 --home-dir /home/runner --shell /bin/bash runner && \
    rm -rf /home/runner/k8s && \
    /home/runner/bin/installdependencies.sh && \
    apt-get update && \
    apt-get install --no-install-recommends --yes libgl1 && \
    rm -rf /var/lib/apt/lists/*
ENV HOME=/home/runner
WORKDIR /home/runner
USER 1001:1001
CMD ["/home/runner/run.sh"]
