FROM ghcr.io/alxleo/base-images/python:3.15-alpine AS build
WORKDIR /app
ENV UV_PYTHON_PREFERENCE=only-system
RUN pip install --no-cache-dir uv==0.13.6
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Retire when the SDK refreshes restored/401-rejected tokens using discovered AS metadata.
COPY oauth-refresh.patch /tmp/oauth-refresh.patch
RUN apk add --no-cache patch \
    && patch --batch --fuzz=0 --directory=/app/.venv/lib/python3.14/site-packages --strip=1 < /tmp/oauth-refresh.patch \
    && rm /tmp/oauth-refresh.patch

FROM ghcr.io/alxleo/base-images/python:3.15-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
ENV PATH="/app/.venv/bin:${PATH}"
COPY --from=build /app/.venv /app/.venv
RUN /usr/local/bin/python3.14 -m pip uninstall --yes pip setuptools \
    && rm -rf /usr/local/lib/python3.14/ensurepip \
    && addgroup -g 1000 -S app \
    && adduser -u 1000 -G app -S -D -s /sbin/nologin app \
    && mkdir /data && chown 1000:1000 /data
COPY server.py healthcheck.py /app/
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python", "/app/healthcheck.py"]
USER 1000
ENTRYPOINT ["python", "/app/server.py"]
