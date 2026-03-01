# PR Reviewer — AI-powered multi-lens code review
#
# Generic image with AI CLIs (Claude, Gemini, Codex) + GitHub CLI + watcher script.
# Config and prompts are mounted at runtime, not baked in.
#
# Mount points:
#   /app/config.yml    — repo allowlist, polling config, lens settings
#   /app/prompts/      — review lens prompt files (*.md)
#
# Secrets (Docker secrets at /run/secrets/):
#   claude_code_oauth_token — Claude Max subscription token (required)
#   gh_token                — GitHub PAT with repo scope (required)
#   gemini_api_key          — Gemini API key (optional)
#   openai_api_key          — OpenAI/Codex API key (optional)

FROM node:22-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    jq \
    python3 \
    python3-yaml \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install AI CLI tools (npm)
RUN npm install -g @anthropic-ai/claude-code @google/gemini-cli

# Install Codex CLI (Rust binary from GitHub releases)
# Pinned version — update when new features needed, Dependabot doesn't track this
ARG CODEX_VERSION=0.106.0
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "amd64" ]; then CODEX_ARCH="x86_64-unknown-linux-musl"; \
       elif [ "$ARCH" = "arm64" ]; then CODEX_ARCH="aarch64-unknown-linux-musl"; \
       else echo "Unsupported architecture: ${ARCH}" >&2; exit 1; fi \
    && curl -fsSL "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${CODEX_ARCH}.tar.gz" \
       | tar xz -C /usr/local/bin/ \
    && mv "/usr/local/bin/codex-${CODEX_ARCH}" /usr/local/bin/codex

# Install gh CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/ scripts/

# State and repos dirs created at runtime via volumes
RUN mkdir -p state repos

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD ["python3", "scripts/healthcheck.py"]

CMD ["python3", "scripts/gh_watcher.py"]
