# Purpose-built Gitea Actions job image for the homelab CI and deployment lanes.
#
# The runner image is intentionally the final base: it supplies the Gitea
# runner's Docker/action runtime and the standard Ubuntu job tools.  This
# image adds the pinned repository toolchain; project dependencies remain the
# checked-out repository's responsibility.

FROM ghcr.io/jdx/mise:2026.8.14@sha256:08c2a808bf88a002a118b5013a21aaab000662f15b1fdad939ea0795724316de AS mise

# Pin the upstream multi-arch Bun index while retaining mise's tool metadata.
FROM oven/bun:1.3.14@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS bun

# docker.gitea.com publishes a multi-platform index; pinning the index keeps
# amd64 and arm64 jobs on the same reviewed upstream release.
FROM docker.gitea.com/runner-images:ubuntu-latest@sha256:fd911d7417bfbf0f454530e447da95b58001e1df41bbc5e1a8dd35d432575aae

LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images" \
      org.opencontainers.image.title="Gitea CI runner job image" \
      org.opencontainers.image.description="Pinned homelab CI and deployment toolchain for Gitea Actions jobs" \
      org.opencontainers.image.base.name="docker.gitea.com/runner-images:ubuntu-latest"

ARG PYTHON_REPO_VERSION=3.13.14
ARG PYTHON_CI_VERSION=3.14.7
ARG NODE_REPO_VERSION=24.21.0
ARG NODE_LATEST_VERSION=26.10.0
ARG BUN_VERSION=1.3.14
ARG UV_VERSION=0.12.19
ARG PRE_COMMIT_VERSION=4.6.2
ARG JUST_VERSION=1.58.0
ARG RUFF_VERSION=0.16.9
ARG CADDY_VERSION=2.11.6
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
ARG HADOLINT_VERSION=2.15.1
ARG TRIVY_VERSION=0.74.0
ARG CONFTEST_VERSION=0.70.1
ARG D2_VERSION=0.8.2
ARG JQ_VERSION=1.8.2
ARG YQ_VERSION=4.53.6
ARG ANSIBLE_CORE_VERSION=2.21.4
ARG JSON_SCHEMA_TO_TYPESCRIPT_VERSION=16.0.0
ARG DEPENDENCY_CRUISER_VERSION=18.4.0
ARG AXE_CORE_CLI_VERSION=4.13.0
ARG JSCPD_VERSION=5.2.1
ARG HELM_VERSION=4.3.0
ARG KUBECTL_VERSION=1.37.1
ARG FLUX2_VERSION=2.9.5
ARG TALOSCTL_VERSION=1.14.1
ARG CILIUM_HUBBLE_VERSION=1.19.4
ARG TERRAFORM_DOCS_VERSION=0.24.0
ARG TFLINT_VERSION=0.64.0
ARG SOPS_VERSION=3.13.3
ARG AGE_VERSION=1.3.2
ARG OPENBAO_VERSION=2.6.2
ARG CLOUDFLARED_VERSION=2026.9.3
ARG RESTIC_VERSION=0.19.1
ARG GH_VERSION=2.100.0
ARG WINDMILL_CLI_VERSION=1.811.1
ARG KYVERNO_VERSION=1.19.1
ARG KUBECONFORM_VERSION=0.8.0
ARG PLUTO_VERSION=5.24.4
ARG ACTIONS_UP_VERSION=1.21.0

# mise npm tools expose their shims under /opt/mise/shims; the Node bin paths
# keep both pinned Node majors and their npm/npx entry points available too.
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
    PATH=/opt/mise/installs/node/24.21.0/bin:/opt/mise/installs/node/26.10.0/bin:/opt/mise/shims:/opt/actions-up/bin:/opt/mise/installs/python/3.13.14/bin:/opt/mise/installs/python/3.14.7/bin:${PATH}

COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise
COPY --from=bun /usr/local/bin/bun /tmp/bun

RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends --yes fd-find ripgrep; \
    rm -rf /var/lib/apt/lists/*; \
    mise use --global --pin --yes \
      "python@${PYTHON_REPO_VERSION}" \
      "python@${PYTHON_CI_VERSION}" \
      "node@${NODE_REPO_VERSION}" \
      "node@${NODE_LATEST_VERSION}" \
      "bun@${BUN_VERSION}" \
      "uv@${UV_VERSION}" \
      "pre-commit@${PRE_COMMIT_VERSION}" \
      "just@${JUST_VERSION}" \
      "ruff@${RUFF_VERSION}" \
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
      "gitleaks@${GITLEAKS_VERSION}" \
      "hadolint@${HADOLINT_VERSION}" \
      "trivy@${TRIVY_VERSION}" \
      "conftest@${CONFTEST_VERSION}" \
      "d2@${D2_VERSION}" \
      "jq@${JQ_VERSION}" \
      "yq@${YQ_VERSION}" \
      "pipx:ansible-core@${ANSIBLE_CORE_VERSION}" \
      "npm:json-schema-to-typescript@${JSON_SCHEMA_TO_TYPESCRIPT_VERSION}" \
      "npm:dependency-cruiser@${DEPENDENCY_CRUISER_VERSION}" \
      "npm:@axe-core/cli@${AXE_CORE_CLI_VERSION}" \
      "npm:jscpd@${JSCPD_VERSION}" \
      "helm@${HELM_VERSION}" \
      "kubectl@${KUBECTL_VERSION}" \
      "flux2@${FLUX2_VERSION}" \
      "talosctl@${TALOSCTL_VERSION}" \
      "cilium-hubble@${CILIUM_HUBBLE_VERSION}" \
      "terraform-docs@${TERRAFORM_DOCS_VERSION}" \
      "tflint@${TFLINT_VERSION}" \
      "sops@${SOPS_VERSION}" \
      "age@${AGE_VERSION}" \
      "openbao@${OPENBAO_VERSION}" \
      "cloudflared@${CLOUDFLARED_VERSION}" \
      "restic@${RESTIC_VERSION}" \
      "gh@${GH_VERSION}" \
      "npm:windmill-cli@${WINDMILL_CLI_VERSION}" \
      "kyverno@${KYVERNO_VERSION}" \
      "kubeconform@${KUBECONFORM_VERSION}" \
      "pluto@${PLUTO_VERSION}"; \
    test "$(/tmp/bun --version)" = "${BUN_VERSION}"; \
    install -Dm755 /tmp/bun "/opt/mise/installs/bun/${BUN_VERSION}/bin/bun"; \
    rm -f /tmp/bun; \
    npm install --global --prefix /opt/actions-up --omit=dev "actions-up@${ACTIONS_UP_VERSION}"; \
    rm -rf /root/.npm "$MISE_CACHE_DIR"; \
    mise reshim; \
    python3.13 --version; \
    python3.14 --version; \
    node --version; \
    test "$(bun --version)" = "${BUN_VERSION}"; \
    test "$(bun -e 'console.log("bun-js-smoke")')" = "bun-js-smoke"; \
    uv --version; \
    mise --version; \
    pre-commit --version; \
    just --version; \
    ruff --version; \
    caddy version; \
    tofu version; \
    shellcheck_output="$(shellcheck --version)"; \
    case "$shellcheck_output" in *"version: ${SHELLCHECK_VERSION}"*) ;; *) exit 1 ;; esac; \
    shfmt --version; \
    yamllint --version; \
    actionlint -version; \
    zizmor --version; \
    cue version; \
    semgrep --version; \
    lychee --version; \
    gitleaks version; \
    hadolint --version; \
    trivy --version; \
    conftest --version; \
    d2 version; \
    jq --version; \
    yq --version; \
    ansible --version; \
    json2ts --help; \
    depcruise --version; \
    axe --version; \
    jscpd --version; \
    helm version --short; \
    kubectl version --client=true; \
    flux --version; \
    talosctl version --client; \
    hubble version; \
    terraform-docs version; \
    tflint --version; \
    sops --version; \
    age --version; \
    bao version; \
    cloudflared version; \
    restic version; \
    gh --version; \
    wmill --version; \
    kyverno version; \
    kubeconform -v; \
    pluto version; \
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
    for npm_cli in json2ts depcruise axe wmill; do command -v "$npm_cli"; done; \
    actions_up_output="$(actions-up --version)"; \
    case "$actions_up_output" in "actions-up/${ACTIONS_UP_VERSION}"*) ;; *) exit 1 ;; esac

USER 1000:1000
