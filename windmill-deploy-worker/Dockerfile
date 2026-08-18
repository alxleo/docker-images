# Trusted Windmill deploy worker with the repository's browser verifier baked in.
# Runtime package installation is impossible under the worker's deliberately
# dropped capabilities, so browser binaries and shared libraries belong here.

# conftest:exempt=user_required -- Windmill workers run as root upstream; the homelab Compose service drops all Linux capabilities and enables no-new-privileges.
FROM ghcr.io/windmill-labs/windmill:1.783.0
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ARG AGENT_BROWSER_VERSION=0.31.2
ARG MISE_VERSION=v2026.7.16
ARG MISE_SHA256=f93483d0e7e0ad6296a5fb2600188d1dadd2c48a4d295af31b69f636a51b92e4
ARG COOLIFY_CLI_VERSION=1.6.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends sudo \
    && npm install -g "agent-browser@${AGENT_BROWSER_VERSION}" \
    && agent-browser install --with-deps \
    && agent-browser --version \
    && SUDO_FORCE_REMOVE=yes apt-get purge -y sudo \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# Coolify key-hygiene flow (homelab #1092): the worker runs
# `mise exec -- coolify` from the runner checkout, whose .mise.toml pins
# github:coollabsio/coolify-cli. Tools live in a fixed MISE_DATA_DIR so the
# hygiene job's HOME override cannot orphan them.
ENV MISE_DATA_DIR=/opt/mise \
    MISE_CACHE_DIR=/opt/mise/cache
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL -o /usr/local/bin/mise \
        "https://github.com/jdx/mise/releases/download/${MISE_VERSION}/mise-${MISE_VERSION}-linux-x64" \
    && echo "${MISE_SHA256}  /usr/local/bin/mise" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/mise \
    && mise install "github:coollabsio/coolify-cli@${COOLIFY_CLI_VERSION}" \
    && mise exec "github:coollabsio/coolify-cli@${COOLIFY_CLI_VERSION}" -- coolify --help >/dev/null
