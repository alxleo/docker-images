# syntax=docker/dockerfile:1.7

# Purpose-built Gitea Actions job image for the homelab CI and deployment lanes.
#
# The runtime is a pinned Ubuntu base with only the job's required system
# packages.  Docker client binaries and Git LFS come from the pinned Gitea
# runner image stage; project dependencies remain the checked-out repository's
# responsibility.
#
# Every tool pin lives in mise.toml, which `mise install` reads below; this
# file holds no tool versions.

FROM ghcr.io/jdx/mise:2026.8.14@sha256:08c2a808bf88a002a118b5013a21aaab000662f15b1fdad939ea0795724316de AS mise

# Pin the upstream multi-arch Bun index while retaining mise's tool metadata.
# This helper stage is mounted into the final RUN and is never published.
# hadolint ignore=DL3049
FROM oven/bun:1.3.14@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS bun

# The pinned Gitea image supplies the reviewed Docker client, Compose, Buildx,
# and Git LFS binaries without bringing its runner tool cache or daemon into
# the final image.
FROM docker.gitea.com/runner-images:ubuntu-latest@sha256:fd911d7417bfbf0f454530e447da95b58001e1df41bbc5e1a8dd35d432575aae AS runner-tools

# Ubuntu publishes a multi-platform index; pinning the mirrored index keeps
# amd64 and arm64 jobs on the same reviewed release.
FROM ghcr.io/alxleo/base-images/ubuntu:24.04@sha256:a853f94d226358a79c740cfc7bce0c289748f3fe3488d921d038ccd752c61b60

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Gitea CI runner job image" \
      org.opencontainers.image.description="Pinned homelab CI and deployment toolchain for Gitea Actions jobs" \
      org.opencontainers.image.base.name="ghcr.io/alxleo/base-images/ubuntu:24.04"

# mise npm tools expose their shims under /opt/mise/shims; the Node and Python
# bin paths keep both pinned majors and their npm/npx entry points available
# too. mise links each installed version under its major (and minor) prefix.
ENV MISE_DATA_DIR=/opt/mise \
    MISE_CONFIG_DIR=/opt/mise \
    MISE_CACHE_DIR=/tmp/mise-cache \
    MISE_AUTO_INSTALL=false \
    MISE_EXEC_AUTO_INSTALL=false \
    MISE_NOT_FOUND_AUTO_INSTALL=false \
    MISE_YES=1 \
    MISE_TRUSTED_CONFIG_PATHS=/workspace \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    HOME=/home/ubuntu \
    PATH=/opt/mise/installs/node/24/bin:/opt/mise/installs/node/26/bin:/opt/mise/shims:/opt/mise/installs/python/3.13/bin:/opt/mise/installs/python/3.14/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

WORKDIR /workspace

COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise
COPY mise.toml /opt/mise/config.toml

# The runner stage supplies the reviewed Docker client, Compose, Buildx, and
# Git LFS binaries without bringing its runner tool cache or daemon into the
# final image.
COPY --from=runner-tools /usr/bin/docker /usr/bin/docker
COPY --from=runner-tools /usr/bin/git-lfs /usr/bin/git-lfs
COPY --from=runner-tools /usr/libexec/docker/cli-plugins/docker-buildx /usr/libexec/docker/cli-plugins/docker-buildx
COPY --from=runner-tools /usr/libexec/docker/cli-plugins/docker-compose /usr/libexec/docker/cli-plugins/docker-compose

RUN set -eux; if ! getent group ubuntu >/dev/null; then groupadd --gid 1000 ubuntu; fi; \
    test "$(getent group ubuntu | cut -d: -f3)" = 1000; \
    if ! getent passwd ubuntu >/dev/null; then useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash ubuntu; fi; \
    test "$(id -u ubuntu)" = 1000

# The optional file secret authenticates mise's GitHub API lookup for trusted
# builds; fork pull requests remain unauthenticated and receive no token.
RUN --mount=type=bind,from=bun,source=/usr/local/bin/bun,target=/tmp/bun \
    --mount=type=secret,id=GITHUB_TOKEN \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eu; \
    apt-get update; \
    apt-get install --no-install-recommends --yes \
        autoconf \
        automake \
        bash \
        bzip2 \
        build-essential \
        ca-certificates \
        curl \
        default-libmysqlclient-dev \
        dpkg-dev \
        fd-find \
        file \
        g++ \
        gcc \
        git \
        gnupg \
        gzip \
        libbz2-dev \
        libc6-dev \
        libcurl4-openssl-dev \
        libdb-dev \
        libevent-dev \
        libffi-dev \
        libgdbm-dev \
        libgmp-dev \
        libjpeg-dev \
        libkrb5-dev \
        liblzma-dev \
        libmaxminddb-dev \
        libncurses5-dev \
        libncursesw5-dev \
        libpng-dev \
        libpq-dev \
        libreadline-dev \
        libsqlite3-dev \
        libssl-dev \
        libtool \
        libwebp-dev \
        libxml2-dev \
        libxslt-dev \
        libyaml-dev \
        lsb-release \
        make \
        netbase \
        openssh-client \
        patch \
        pkg-config \
        procps \
        ripgrep \
        sq \
        sudo \
        tar \
        tzdata \
        unzip \
        wget \
        xz-utils \
        zip \
        zstd \
        zlib1g-dev; \
    usermod --append --groups sudo ubuntu; \
    printf '%s\n' 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu; \
    chmod 0440 /etc/sudoers.d/ubuntu; \
    mkdir -p /workspace; \
    chown 1000:1000 /home/ubuntu /workspace; \
    if [ -s /run/secrets/GITHUB_TOKEN ]; then \
        GITHUB_TOKEN="$(cat /run/secrets/GITHUB_TOKEN)"; \
        export GITHUB_TOKEN; \
    fi; \
    mise install; \
    unset GITHUB_TOKEN; \
    set -x; \
    bun_dir="$(mise where bun)"; \
    test "$(/tmp/bun --version)" = "${bun_dir##*/}"; \
    install -Dm755 /tmp/bun "${bun_dir}/bin/bun"; \
    rm -rf /root/.cache /root/.npm /home/ubuntu/.cache /home/ubuntu/.npm /tmp/node-compile-cache "$MISE_CACHE_DIR"; \
    chown -R 1000:1000 /home/ubuntu /workspace; \
    mise reshim; \
    test -z "$(mise ls --missing)"

# Keep explicit names for workflows that need both supported Node majors while
# making the repository-pinned Node 24 the default `node`/`npm` on PATH.
RUN set -eux; \
    ln -sfn "$(command -v python3.13)" /usr/local/bin/python; \
    ln -sfn "$(command -v python3.13)" /usr/local/bin/python3; \
    ln -sfn "$(command -v node)" /usr/local/bin/node24; \
    ln -sfn npm /opt/mise/installs/node/24/bin/npm24; \
    ln -sfn npx /opt/mise/installs/node/24/bin/npx24; \
    ln -sfn /opt/mise/installs/node/26/bin/node /usr/local/bin/node26; \
    ln -sfn npm /opt/mise/installs/node/26/bin/npm26; \
    ln -sfn npx /opt/mise/installs/node/26/bin/npx26

USER 1000:1000
