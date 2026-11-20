ARG OPEN_TERMINAL_IMAGE=ghcr.io/open-webui/open-terminal:0.17.20-openshift@sha256:3e6e9746d861a79a4f2a1d8554c807c9adc93947624988b28901586bd19c9928
FROM ${OPEN_TERMINAL_IMAGE} AS release
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) asset=opencode-linux-x64-baseline.tar.gz; digest=8443113b3f3dfebf8b0fa91c4377e5519a62b9231732d9344a5df001e4a852b3 ;; \
      arm64) asset=opencode-linux-arm64.tar.gz; digest=5b68c1f4c5e75b4134e664cc8f36d634d64208d4fcfe5bcf3b48bab699c2dbac ;; \
      *) printf 'Unsupported architecture: %s\n' "$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl --fail --silent --show-error --location --proto '=https' --max-time 120 \
      "https://github.com/anomalyco/opencode/releases/download/v1.19.6/$asset" -o /tmp/opencode.tar.gz; \
    printf '%s  %s\n' "$digest" /tmp/opencode.tar.gz > /tmp/opencode.sha256; \
    sha256sum --check /tmp/opencode.sha256; \
    tar -xzf /tmp/opencode.tar.gz -C /tmp opencode

FROM ${OPEN_TERMINAL_IMAGE}
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
USER 0:0
RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*
COPY --from=release --chmod=0755 /tmp/opencode /usr/local/bin/opencode
ENV OPENCODE_DISABLE_AUTOUPDATE=true
# user-has-group:exempt=1001 -- restore the upstream OpenShift image's non-root user and root-group filesystem access
USER 1001
