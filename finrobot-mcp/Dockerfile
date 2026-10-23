# FinRobot V2 API plus its thin native OpenAPI-to-MCP facade.
FROM ghcr.io/alxleo/base-images/python:3.14-slim

LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ENV HOME=/home/app \
    PYTHONPATH=/app \
    FINROBOT_CACHE_DB_PATH=/cache/finrobot/data_cache.db \
    FINROBOT_API_PORT=8000 \
    FINROBOT_MCP_PORT=8080 \
    FINROBOT_API_URL=http://127.0.0.1:8000

COPY pyproject.toml uv.lock /opt/finrobot-dependencies/

# Refresh vendor security packages, including the CA store, before fetching Python dependencies.
# hadolint ignore=DL3005
RUN apt-get update \
    && apt-get upgrade --no-install-recommends -y \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade "pip==26.2.2" "uv==0.13.4" \
    && uv export --quiet --directory /opt/finrobot-dependencies --frozen --no-dev --no-emit-project --output-file /tmp/finrobot-requirements.txt \
    && uv pip install --system --no-cache-dir --requirement /tmp/finrobot-requirements.txt \
    && uv pip check --system \
    && uv pip uninstall --system uv pip \
    && rm -rf /tmp/finrobot-requirements.txt /opt/finrobot-dependencies \
    && apt-get purge --auto-remove -y git \
    && addgroup --gid 1000 app \
    && adduser --uid 1000 --gid 1000 --disabled-password --gecos '' --shell /usr/sbin/nologin app \
    && mkdir -p /home/app/.finrobot /cache/finrobot /data /tmp \
    && chown -R 1000:1000 /home/app /cache /data /tmp

COPY finrobot_mcp.py /app/finrobot_mcp.py
COPY entrypoint.sh /usr/local/bin/finrobot-entrypoint
COPY healthcheck.py /app/healthcheck.py
RUN chmod 0755 /usr/local/bin/finrobot-entrypoint /app/healthcheck.py

EXPOSE 8000 8080

HEALTHCHECK --interval=30s --timeout=8s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

USER 1000:1000
ENTRYPOINT ["finrobot-entrypoint"]
CMD ["api"]
