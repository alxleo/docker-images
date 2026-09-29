# Purpose-built Gitea Actions job image for the Python/Node-heavy CI lanes.
#
# The runner image is intentionally the final base: it supplies the Gitea
# runner's Docker/action runtime and the standard Ubuntu job tools.  This
# image only adds the pinned repository toolchain; project dependencies remain
# the checked-out repository's responsibility.

FROM ghcr.io/jdx/mise:2026.8.14@sha256:08c2a808bf88a002a118b5013a21aaab000662f15b1fdad939ea0795724316de AS mise

# docker.gitea.com publishes a multi-platform index; pinning the index keeps
# amd64 and arm64 jobs on the same reviewed upstream release.
FROM docker.gitea.com/runner-images:ubuntu-latest@sha256:fd911d7417bfbf0f454530e447da95b58001e1df41bbc5e1a8dd35d432575aae

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Gitea CI runner job image" \
      org.opencontainers.image.description="Pinned Python and Node toolchain for Gitea Actions jobs" \
      org.opencontainers.image.base.name="docker.gitea.com/runner-images:ubuntu-latest"

ARG PYTHON_REPO_VERSION=3.13.14
ARG PYTHON_CI_VERSION=3.14.7
ARG NODE_REPO_VERSION=24.21.0
ARG NODE_LATEST_VERSION=26.10.0
ARG UV_VERSION=0.12.19
ARG PRE_COMMIT_VERSION=4.6.2
ARG JUST_VERSION=1.58.0
ARG CADDY_VERSION=2.11.4
ARG OPENTOFU_VERSION=1.12.6
ARG SHELLCHECK_VERSION=0.11.0
ARG SHFMT_VERSION=3.14.1
ARG YAMLLINT_VERSION=1.38.0
ARG ACTIONLINT_VERSION=1.7.12
ARG ZIZMOR_VERSION=1.30.1
ARG CUE_VERSION=0.17.1
ARG SEMGREP_VERSION=1.177.0
ARG LYCHEE_VERSION=0.23.0
ARG GITLEAKS_VERSION=8.30.1
ARG ACTIONS_UP_VERSION=1.21.0

ENV MISE_DATA_DIR=/opt/mise \
    MISE_CONFIG_DIR=/opt/mise \
    MISE_CACHE_DIR=/tmp/mise-cache \
    MISE_YES=1 \
    MISE_TRUSTED_CONFIG_PATHS=/workspace \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PATH=/opt/mise/installs/node/24.21.0/bin:/opt/mise/installs/node/26.10.0/bin:/opt/mise/shims:/opt/actions-up/bin:/opt/mise/installs/python/3.13.14/bin:/opt/mise/installs/python/3.14.7/bin:${PATH}

COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise

RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends --yes fd-find ripgrep; \
    rm -rf /var/lib/apt/lists/*; \
    mise use --global --pin --yes \
      "python@${PYTHON_REPO_VERSION}" \
      "python@${PYTHON_CI_VERSION}" \
      "node@${NODE_REPO_VERSION}" \
      "node@${NODE_LATEST_VERSION}" \
      "uv@${UV_VERSION}" \
      "pre-commit@${PRE_COMMIT_VERSION}" \
      "just@${JUST_VERSION}" \
      "caddy@${CADDY_VERSION}" \
      "opentofu@${OPENTOFU_VERSION}" \
      "shellcheck@${SHELLCHECK_VERSION}" \
      "shfmt@${SHFMT_VERSION}" \
      "yamllint@${YAMLLINT_VERSION}" \
      "actionlint@${ACTIONLINT_VERSION}" \
      "zizmor@${ZIZMOR_VERSION}" \
      "cue@${CUE_VERSION}" \
      "semgrep@${SEMGREP_VERSION}" \
      "lychee@${LYCHEE_VERSION}" \
      "gitleaks@${GITLEAKS_VERSION}"; \
    npm install --global --prefix /opt/actions-up --omit=dev "actions-up@${ACTIONS_UP_VERSION}"; \
    rm -rf /root/.npm "$MISE_CACHE_DIR"; \
    mise reshim; \
    python3.13 --version; \
    python3.14 --version; \
    node --version; \
    uv --version; \
    mise --version; \
    pre-commit --version; \
    just --version; \
    caddy version; \
    tofu version; \
    shellcheck --version | head -1; \
    shfmt --version; \
    yamllint --version; \
    actionlint -version; \
    zizmor --version; \
    cue version; \
    semgrep --version; \
    lychee --version; \
    gitleaks version; \
    actions-up --version

# Keep explicit names for workflows that need both supported Node majors while
# making the repository-pinned Node 24 the default `node`/`npm` on PATH.
RUN set -eux; \
    ln -sfn "$(command -v python3.13)" /usr/local/bin/python; \
    ln -sfn "$(command -v python3.13)" /usr/local/bin/python3; \
    ln -sfn "$(command -v node)" /usr/local/bin/node24; \
    ln -sfn npm /opt/mise/installs/node/24.21.0/bin/npm24; \
    ln -sfn npx /opt/mise/installs/node/24.21.0/bin/npx24; \
    ln -sfn /opt/mise/installs/node/26.10.0/bin/node /usr/local/bin/node26; \
    ln -sfn npm /opt/mise/installs/node/26.10.0/bin/npm26; \
    ln -sfn npx /opt/mise/installs/node/26.10.0/bin/npx26; \
    test "$(node24 --version)" = "v24.21.0"; \
    test "$(node26 --version)" = "v26.10.0"; \
    actions-up --version | grep -Eq '^actions-up/1\.21\.0([[:space:]]|$)'

USER ubuntu
