# miniflux-enricher — translate foreign entries + drop SEO/listicle junk in-place.
#
# A small FastAPI webhook worker. Miniflux fires `new_entries` (HMAC-signed);
# this acks in <10s and processes async against the homelab's LOCAL inference
# (translategemma for translation, granite4 for junk classification). Enriched
# content goes back via the Miniflux API (PUT /v1/entries). No credentials to
# third parties; read-only against the internet (fetches nothing itself).

FROM ghcr.io/alxleo/base-images/python:3.13-alpine AS build
RUN pip install --no-cache-dir uv==0.12.0

FROM ghcr.io/alxleo/base-images/python:3.13-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

# Healthcheck binary: 75KB static C/musl, localhost-only by design
COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

COPY --from=build /usr/local/bin/uv /usr/local/bin/uv
RUN uv pip install --system --break-system-packages \
    "fastapi>=0.115" \
    "uvicorn>=0.32" \
    "httpx>=0.27"

COPY app.py /app/app.py
WORKDIR /app

EXPOSE 8080
ENV ENRICHER_PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/ping"]

# Matching uid=1000/gid=1000 app user (base python:alpine ships none — see mcp-substack)
RUN addgroup -g 1000 -S app \
    && adduser -u 1000 -G app -S -D -s /sbin/nologin app
USER app

ENTRYPOINT ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${ENRICHER_PORT:-8080}"]
