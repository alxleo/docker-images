# Trusted Windmill deploy worker with the repository's browser verifier baked in.
# Runtime package installation is impossible under the worker's deliberately
# dropped capabilities, so browser binaries and shared libraries belong here.

# conftest:exempt=user_required -- Windmill workers run as root upstream; the homelab Compose service drops all Linux capabilities and enables no-new-privileges.
FROM ghcr.io/windmill-labs/windmill:1.783.0
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ARG AGENT_BROWSER_VERSION=0.31.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends sudo \
    && npm install -g "agent-browser@${AGENT_BROWSER_VERSION}" \
    && agent-browser install --with-deps \
    && agent-browser --version \
    && SUDO_FORCE_REMOVE=yes apt-get purge -y sudo \
    && rm -rf /var/lib/apt/lists/* /root/.npm
