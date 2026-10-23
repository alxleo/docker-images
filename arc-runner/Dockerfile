# syntax=docker/dockerfile:1.7

FROM ghcr.io/actions/actions-runner:2.338.0@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807 AS runner
FROM ghcr.io/alxleo/gitea-ci-runner@sha256:ef4791975ae19034aae5d0d79c9faa30bd0f7974f0d1963e1952337aadf185d8

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Disposable ARC runner" \
      org.opencontainers.image.description="Released GitHub runner with the shared homelab CI toolchain"

USER 0:0
COPY --from=runner --chown=1001:1001 /home/runner /home/runner
RUN groupadd --gid 1001 runner && \
    useradd --uid 1001 --gid 1001 --home-dir /home/runner --shell /bin/bash runner && \
    rm -rf /home/runner/k8s && \
    /home/runner/bin/installdependencies.sh && \
    rm -rf /var/lib/apt/lists/*
ENV HOME=/home/runner
WORKDIR /home/runner
USER 1001:1001
CMD ["/home/runner/run.sh"]
