# Native OpenBB MCP server. Keep the upstream launcher and its /mcp endpoint.
FROM ghcr.io/alxleo/base-images/python:3.14-slim

LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

ENV HOME=/home/app \
    XDG_CACHE_HOME=/cache \
    OPENBB_MCP_ALLOWED_TOOL_CATEGORIES=bls,cboe,ecb,fred,imf,nasdaq,sec \
    OPENBB_MCP_DEFAULT_TOOL_CATEGORIES=bls,cboe,ecb,fred,imf,nasdaq,sec \
    OPENBB_MCP_DEFAULT_SKILLS_DIR= \
    OPENBB_MCP_ENABLE_CLI_TOOLS=false \
    OPENBB_SEC_CACHE_DIR=/cache/sec \
    OPENBB_FRED_DISK_CACHE_DIR=/cache/fred \
    OPENBB_ECB_CACHE_DIR=/cache/ecb \
    MCP_PORT=8080

COPY disable_mutating_tools.py /tmp/disable_mutating_tools.py
COPY healthcheck.py /app/healthcheck.py

RUN pip install --no-cache-dir \
        "openbb-core==2.0.1" \
        "openbb-mcp-server==2.0.1" \
        "openbb-sec==2.0.0" \
        "openbb-fred==2.0.0" \
        "openbb-ecb==2.0.0" \
        "openbb-imf==3.0.0" \
        "openbb-cboe==2.0.0" \
        "openbb-nasdaq==2.0.0" \
        "openbb-bls==2.0.0" \
    && python /tmp/disable_mutating_tools.py \
    && rm -f /tmp/disable_mutating_tools.py \
    && addgroup --gid 1000 app \
    && adduser --uid 1000 --gid 1000 --disabled-password --gecos '' --shell /usr/sbin/nologin app \
    && mkdir -p /home/app/.openbb_platform /cache/http /cache/sec /cache/fred /cache/ecb /data /tmp \
    && printf '%s\n' '{"credentials": {}, "preferences": {"cache_directory": "/cache", "data_directory": "/data", "export_directory": "/data/exports", "user_styles_directory": "/data/styles/user"}, "defaults": {"commands": {}}}' > /home/app/.openbb_platform/user_settings.json \
    && printf '%s\n' '{}' > /home/app/.openbb_platform/system_settings.json \
    && chown -R 1000:1000 /home/app /cache /data /tmp

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=8s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

USER 1000:1000
ENTRYPOINT ["openbb-mcp"]
CMD ["--host", "0.0.0.0", "--port", "8080", "--transport", "streamable-http"]
