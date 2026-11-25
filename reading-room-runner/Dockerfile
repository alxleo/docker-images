# syntax=docker/dockerfile:1.28

# The ARC runner with the reading-room repository's CI toolchain already in
# place, so its jobs stop downloading about 760 MB on every run.
#
# Every version comes from a copy of that repository's pins beside this file:
# mise.toml and mise.lock for its mise tools and Qt lines, rust-toolchain.toml
# for Rust, aqt-requirements.txt for the Qt installer. The repository checks
# what is here and downloads whatever is missing, so a stale image is slower,
# never wrong.

# The :latest tag lets Renovate move the digest when arc-runner publishes; a
# build tag never changes digest, so Renovate would leave it pinned for good.
FROM ghcr.io/alxleo/arc-runner:latest@sha256:7e84052c68008b9468fd1fa17877a9cd89e50f58b2f7092b772fbc9063bbdded AS runner

# The Qt SDKs install in their own stage, so the installer and its archives
# never reach the image. aqt writes the install path into qmake, so they
# install at the path the image keeps them at.
#
# Every build of the same Qt versions yields a byte-identical Qt layer, so a
# base or tool update re-downloads only the small layers on each node. The
# finished tree moves under /tmp/qt-layer with every timestamp fixed, /opt
# included, and the final stage copies that folder's contents as a layer of
# its own (COPY --link); copying only the SDK folder would stamp the /opt
# entry COPY creates with the build time.
FROM runner AS qt
ARG TARGETARCH
# This stage only installs files for the final stage to copy; it never runs.
# hadolint ignore=DL3002
USER 0:0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /tmp
COPY mise.toml aqt-requirements.txt /tmp/pins/
# qmake loads GLib, which the base image lacks; the final stage adds it too.
RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends --yes libglib2.0-0t64; \
    rm -rf /var/lib/apt/lists/*; \
    case "$TARGETARCH" in \
        amd64) host=linux; arch=linux_gcc_64; folder=gcc_64 ;; \
        arm64) host=linux_arm64; arch=linux_gcc_arm64; folder=gcc_arm64 ;; \
        *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    export UV_CACHE_DIR=/tmp/uv-cache; \
    uv venv --quiet --python "$(command -v python3.13)" /tmp/aqt; \
    uv pip install --quiet --python /tmp/aqt/bin/python --require-hashes -r /tmp/pins/aqt-requirements.txt; \
    for version in $(/tmp/aqt/bin/python -c 'import sys, tomllib; env = tomllib.load(open(sys.argv[1], "rb"))["env"]; print(env["QT_VERSION"], env["QT_COMPAT_VERSION"])' /tmp/pins/mise.toml); do \
        /tmp/aqt/bin/python -m aqt install-qt "$host" desktop "$version" "$arch" \
            --archives qtbase qtdeclarative qtsvg icu --outputdir /opt/reading-room-qt; \
        test "$("/opt/reading-room-qt/$version/$folder/bin/qmake" -query QT_VERSION)" = "$version"; \
        touch "/opt/reading-room-qt/$version/$folder/.reading-room-sdk-v2-complete"; \
    done; \
    rm -f /tmp/aqtinstall.log; \
    mkdir -p /tmp/qt-layer/opt; \
    mv /opt/reading-room-qt /tmp/qt-layer/opt/; \
    find /tmp/qt-layer -mindepth 1 -exec touch --no-dereference --date=@0 {} +

FROM runner

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Reading-room ARC runner" \
      org.opencontainers.image.description="Disposable ARC runner with the reading-room repository's Qt SDKs, Rust and mise tools preinstalled"

USER 0:0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Read-only and root-owned: the repository's installer only reads this tree.
# The jobs put the repository's own runtime libraries first when they run Qt;
# the system GLib lets qmake answer a query in the image without them.
COPY --link --from=qt /tmp/qt-layer/ /
RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends --yes libglib2.0-0t64; \
    rm -rf /var/lib/apt/lists/*
COPY mise.toml mise.lock rust-toolchain.toml /opt/reading-room/

# The repository's mise tools install beside the base image's, from the copied
# lock, as a project would. The new directories then change hands like the
# base image's (see arc-runner), so a job can still add versions in place.
# Root's own HOME keeps mise's state files out of the job user's home.
RUN set -eux; \
    HOME=/root MISE_CACHE_DIR=/tmp/mise-cache MISE_TRUSTED_CONFIG_PATHS=/opt/reading-room MISE_LOCKED_SCOPES=project \
        mise --cd /opt/reading-room install --locked python uv shellcheck cmake actionlint node pixi zig; \
    rm -rf /tmp/mise-cache /root/.cache /root/.local; \
    find /opt/mise/installs /opt/mise/shims /opt/mise/downloads -xdev -type d ! -user 1001 -exec chown 1001:1001 {} +; \
    install -d -o 1001 -g 1001 /opt/rustup /opt/cargo

# Rust belongs to the job's user outright: rustup rewrites a toolchain's
# manifests when it adds a component or target, a toolchain bump installs
# beside this one, and rust-cache restores the registry into CARGO_HOME.
ENV RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    PATH=/opt/cargo/bin:${PATH}

# user-has-group:exempt=1001 -- arc-runner creates the runner user and group as 1001:1001.
USER 1001:1001
ARG TARGETARCH
# Not RUSTUP_VERSION: rustup reads that name as a self-update pin.
ARG RUSTUP_INIT_VERSION=1.29.3
# rustup installs the toolchain file's channel, components and targets only
# from the file's own directory.
# hadolint ignore=DL3003
RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) triple=x86_64-unknown-linux-gnu; sha=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55 ;; \
        arm64) triple=aarch64-unknown-linux-gnu; sha=9f608c142e0e38a78957d0661ba1dfaf0b6fb37184cfaa4b9a0aa57af6184282 ;; \
        *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    scratch="$(mktemp -d)"; \
    curl --proto '=https' --tlsv1.2 -fsSLo "$scratch/rustup-init" \
        "https://static.rust-lang.org/rustup/archive/$RUSTUP_INIT_VERSION/$triple/rustup-init"; \
    echo "$sha  $scratch/rustup-init" | sha256sum -c -; \
    chmod +x "$scratch/rustup-init"; \
    "$scratch/rustup-init" -y --no-modify-path --profile minimal --default-toolchain none; \
    cp /opt/reading-room/rust-toolchain.toml "$scratch/"; \
    (cd "$scratch" && rustup toolchain install); \
    rustup default "$(sed -n 's/^channel = "\(.*\)"$/\1/p' /opt/reading-room/rust-toolchain.toml)"; \
    rm -rf "$scratch" "$RUSTUP_HOME/downloads" "$RUSTUP_HOME/tmp"

# No warm Zig cache: Zig 0.17 keys the libc sources it compiled by inode, which
# changes when a node unpacks the image, so a baked cache is rebuilt in full.

ENV READING_ROOM_QT_SDKS=/opt/reading-room-qt
WORKDIR /home/runner
