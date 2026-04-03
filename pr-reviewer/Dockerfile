# PR Reviewer — AI-powered multi-lens code review
#
# Generic image with AI CLIs (Claude, Gemini, Codex) + forge CLIs (gh, glab) +
# code search tools (ripgrep, fd) for quality AI-assisted PR review.
#
# Default prompts baked in; override via volume mount at /app/prompts/.
# Plugins loaded via --plugin-dir at runtime; cache in /app/plugins/ volume.
#
# Entrypoints:
#   python3 scripts/gh_watcher.py      — GitHub poller (default CMD)
#   python3 scripts/gitea_webhook.py   — Gitea webhook handler
#
# Mount points:
#   /app/config.yml    — repo allowlist, polling config, lens settings
#   /app/prompts/      — review lens prompt files (*.md) — override baked-in defaults
#   /app/plugins/      — Claude Code plugins (skills, agents) — persisted across runs
#
# Secrets (Docker secrets at /run/secrets/ or env vars):
#   claude_code_oauth_token    — Claude Max subscription token (required)
#   gh_app_id                  — GitHub App numeric ID (GitHub mode only)
#   gh_app_installation_id     — GitHub App installation ID (GitHub mode only)
#   gh_app_private_key         — GitHub App PEM private key (GitHub mode only)
#   gemini_api_key             — Gemini API key (optional)
#   openai_api_key             — OpenAI/Codex API key (optional)

FROM ghcr.io/alxleo/base-images/node:22-slim
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# System packages: git, code search (ripgrep, fd), JSON processing, Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    jq \
    ripgrep \
    fd-find \
    python3 \
    python3-pip \
    python3-yaml \
    ca-certificates \
    curl \
    && pip3 install --no-cache-dir --break-system-packages \
       "PyJWT[crypto]==2.11.0" "httpx==0.28.1" "grep-ast==0.9.0" \
    && rm -rf /var/lib/apt/lists/* \
    # fd-find installs as fdfind on Debian — symlink to fd for Claude Code
    && ln -sf /usr/bin/fdfind /usr/bin/fd

# Install AI CLI tools (npm)
RUN npm install -g @anthropic-ai/claude-code @google/gemini-cli

# Install Codex CLI (Rust binary from GitHub releases)
# Pinned version + SHA256 — update both when bumping
ARG CODEX_VERSION=0.106.0
ARG CODEX_SHA256_AMD64=157a19dc3b4dffd55f8217e307e067acd588083bcb91177c0d12aa0288d6b9d2
ARG CODEX_SHA256_ARM64=c204fc78805264130fdd630df3fb38a92b9676284b82642510374c363d4679f4
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "amd64" ]; then CODEX_ARCH="x86_64-unknown-linux-musl"; EXPECTED="$CODEX_SHA256_AMD64"; \
       elif [ "$ARCH" = "arm64" ]; then CODEX_ARCH="aarch64-unknown-linux-musl"; EXPECTED="$CODEX_SHA256_ARM64"; \
       else echo "Unsupported architecture: ${ARCH}" >&2; exit 1; fi \
    && curl -fsSL "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${CODEX_ARCH}.tar.gz" \
       -o /tmp/codex.tar.gz \
    && echo "${EXPECTED}  /tmp/codex.tar.gz" | sha256sum -c - \
    && tar xzf /tmp/codex.tar.gz -C /usr/local/bin/ \
    && mv "/usr/local/bin/codex-${CODEX_ARCH}" /usr/local/bin/codex \
    && rm /tmp/codex.tar.gz

# Install gh CLI (GitHub)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Install glab CLI (GitLab)
ARG GLAB_VERSION=1.89.0
RUN ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_${ARCH}.deb" \
       -o /tmp/glab.deb \
    && dpkg -i /tmp/glab.deb \
    && rm /tmp/glab.deb

# Install ast-grep (structural code search via AST patterns)
# Pinned version + SHA256 — update both when bumping
ARG AST_GREP_VERSION=0.42.0
ARG SG_SHA256_AMD64=e825a05603f0bcc4cd9076c4cc8c9abd6d008b7cd07d9aa3cc323ba4b8606651
ARG SG_SHA256_ARM64=5c830eae8456569e2f7212434ed9c238f58dca412d76045418ed6d394a755836
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "amd64" ]; then SG_ARCH="x86_64-unknown-linux-gnu"; EXPECTED="$SG_SHA256_AMD64"; \
       elif [ "$ARCH" = "arm64" ]; then SG_ARCH="aarch64-unknown-linux-gnu"; EXPECTED="$SG_SHA256_ARM64"; \
       else echo "Unsupported: ${ARCH}" >&2; exit 1; fi \
    && curl -fsSL "https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-${SG_ARCH}.zip" \
       -o /tmp/sg.zip \
    && echo "${EXPECTED}  /tmp/sg.zip" | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends unzip \
    && unzip -j /tmp/sg.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/sg \
    && rm /tmp/sg.zip \
    && apt-get purge -y unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/ scripts/
COPY prompts/ prompts/
COPY plugin/ plugin/

# State, repos, and plugins dirs — mount as volumes for persistence
# ~/.gemini and ~/.codex needed by their respective CLIs
RUN mkdir -p state repos plugins /root/.gemini /root/.codex

USER 1000

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD ["python3", "scripts/healthcheck.py"]

CMD ["python3", "scripts/gh_watcher.py"]
