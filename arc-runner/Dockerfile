# syntax=docker/dockerfile:1.7

FROM ghcr.io/actions/actions-runner:2.338.1@sha256:e275409999c37162649aa050ca573f03eab2eabcb3a1e7fcc47548de6b4f9690 AS runner
FROM ghcr.io/alxleo/gitea-ci-runner@sha256:ab28d579feba5b8f8f0dfbab70f101fdb27372f6441ac0ac38dc23232abe7313

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
