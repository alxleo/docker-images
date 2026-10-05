# FinRobot V2 API plus its thin native OpenAPI-to-MCP facade.
FROM ghcr.io/alxleo/base-images/python:3.14-slim

LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ENV HOME=/home/app \
    PYTHONPATH=/app \
    FINROBOT_CACHE_DB_PATH=/cache/finrobot/data_cache.db \
    FINROBOT_API_PORT=8000 \
    FINROBOT_MCP_PORT=8080 \
    FINROBOT_API_URL=http://127.0.0.1:8000

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "uv==0.12.22" \
    && git clone --filter=blob:none --no-checkout https://github.com/AI4Finance-Foundation/FinRobot.git /opt/finrobot-source \
    && git -C /opt/finrobot-source checkout --detach 2717499b8e30f242640af08c4ad9afd1113c2d45 \
    && test "$(git -C /opt/finrobot-source rev-parse HEAD)" = "2717499b8e30f242640af08c4ad9afd1113c2d45" \
    && uv export --directory /opt/finrobot-source/finrobot_desktop --frozen --no-dev --no-emit-project --no-hashes --output-file /tmp/finrobot-constraints.txt \
    && uv pip install --system --no-cache-dir --constraint /tmp/finrobot-constraints.txt /opt/finrobot-source/finrobot_desktop \
        "fastmcp==3.1.1" \
    && rm -f /tmp/finrobot-constraints.txt \
    && rm -rf /opt/finrobot-source \
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

USER app
ENTRYPOINT ["finrobot-entrypoint"]
CMD ["api"]
