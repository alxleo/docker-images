# syntax=docker/dockerfile:1.7

FROM ghcr.io/actions/actions-runner:2.338.0@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807 AS runner
FROM ghcr.io/alxleo/gitea-ci-runner:latest@sha256:7fdf3164bd9f24dbb581bca69a98b3fa639e62f311ebab0179f23667d945e552

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Disposable ARC runner" \
      org.opencontainers.image.description="Released GitHub runner with the shared homelab CI toolchain"

USER root
COPY --from=runner --chown=1001:1001 /home/runner /home/runner
RUN groupadd --gid 1001 runner && \
    useradd --uid 1001 --gid 1001 --home-dir /home/runner --shell /bin/bash runner && \
    rm -rf /home/runner/k8s && \
    /home/runner/bin/installdependencies.sh && \
    apt-get update && \
    apt-get install --no-install-recommends --yes libgl1 && \
    rm -rf /var/lib/apt/lists/*
# The pod is disposable and runs one job, so the job owns the tool tree: a locked
# install adds versions beside the baseline in place and repoints their major and
# minor aliases, which mise also repairs when nothing new installs. Only the
# directories change hands; the baseline's files stay root-owned, and so do the
# global config and lock beside them.
RUN find /opt/mise/installs /opt/mise/shims /opt/mise/downloads -xdev -type d -exec chown 1001:1001 {} +
# A project install downloads several hundred megabytes of archives and package
# caches. The pod's /tmp is a small volume, so they go to its work volume, whose
# mount point does not exist in the image.
ENV HOME=/home/runner \
    MISE_CACHE_DIR=/home/runner/_work/.mise-cache
WORKDIR /home/runner
USER 1001:1001
CMD ["/home/runner/run.sh"]
