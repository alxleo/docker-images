# syntax=docker/dockerfile:1.7
FROM ghcr.io/alxleo/base-images/node:26-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts && npm cache clean --force

FROM ghcr.io/alxleo/base-images/alpine:3.23 AS renderers
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
ARG TARGETARCH
ARG D2_VERSION=0.7.1
ARG D2_AMD64_SHA256=eb172adf59f38d1e5a70ab177591356754ffaf9bebb84e0ca8b767dfb421dad7
ARG D2_ARM64_SHA256=ce3a0b985a8f91335a826c254b3a88736fd81afcdd08b58f6c749d2add6864b0
ARG PLANTUML_VERSION=1.2026.6
ARG PLANTUML_SHA256=89948f14c93756c7a3fb7b69078ff37e8489fd79dd430c582b931e2f65358690
RUN apk add --no-cache ca-certificates curl \
    && case "${TARGETARCH}" in \
         amd64) D2_SHA256="${D2_AMD64_SHA256}" ;; \
         arm64) D2_SHA256="${D2_ARM64_SHA256}" ;; \
         *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/d2.tar.gz \
       "https://github.com/terrastruct/d2/releases/download/v${D2_VERSION}/d2-v${D2_VERSION}-linux-${TARGETARCH}.tar.gz" \
    && echo "${D2_SHA256}  /tmp/d2.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/d2.tar.gz -C /tmp \
    && install -m 0755 "/tmp/d2-v${D2_VERSION}/bin/d2" /usr/local/bin/d2 \
    && curl -fsSL -o /opt/plantuml.jar \
       "https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml.jar" \
    && echo "${PLANTUML_SHA256}  /opt/plantuml.jar" | sha256sum -c - \
    && rm -rf /tmp/d2*

FROM ghcr.io/alxleo/base-images/node:26-alpine
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
RUN apk add --no-cache ca-certificates ffmpeg graphviz openjdk17-jre su-exec
RUN deluser node
RUN addgroup -g 1000 app \
    && adduser -D -u 1000 -G app app \
    && mkdir -p /app /state /config \
    && chown -R 1000:1000 /app /state /config
WORKDIR /app
ENV NODE_ENV=production \
    ASTRO_TELEMETRY_DISABLED=1 \
    DOCS_HUB_PORT=8080 \
    DOCS_HUB_STATE_DIR=/state \
    DOCS_HUB_CONFIG_ROOT=/config \
    DOCS_HUB_SITE_URL=http://localhost:8080 \
    DOCS_HUB_ASSET_ORIGIN=http://localhost:8081 \
    DOCS_HUB_GITEA_URL=http://localhost:3000
COPY --chown=1000:1000 --from=dependencies /app/node_modules ./node_modules
COPY --from=renderers /usr/local/bin/d2 /usr/local/bin/d2
COPY --from=renderers /opt/plantuml.jar /opt/plantuml.jar
COPY --chown=1000:1000 astro.config.mjs package.json package-lock.json ./
COPY --chown=1000:1000 server ./server
COPY --chown=1000:1000 scripts ./scripts
COPY --chown=1000:1000 src ./src
COPY --chown=1000:1000 fixtures ./fixtures
RUN d2 --layout=elk --theme=0 fixtures/public/visuals/flow.d2 fixtures/public/visuals/d2.svg \
    && dot -Tsvg fixtures/public/visuals/flow.dot -o fixtures/public/visuals/dot.svg \
    && java -Djava.awt.headless=true -jar /opt/plantuml.jar \
       -tsvg -pipe < fixtures/public/visuals/flow.puml > fixtures/public/visuals/plantuml.svg \
    && ffmpeg -nostdin -loglevel error -f lavfi -i anullsrc=r=8000:cl=mono -t 1 \
       -flags bitexact -fflags bitexact -metadata creation_time=1970-01-01T00:00:00Z \
       fixtures/public/visuals/silent.wav \
    && ffmpeg -nostdin -loglevel error -f lavfi -i color=c=0x6d5dfc:s=640x360 \
       -frames:v 1 -flags bitexact -fflags bitexact fixtures/public/visuals/raster.png \
    && ffmpeg -nostdin -loglevel error -f lavfi -i color=c=0x111827:s=320x180:r=10 -t 1 \
       -an -c:v libx264 -pix_fmt yuv420p -flags bitexact -fflags bitexact \
       -metadata creation_time=1970-01-01T00:00:00Z fixtures/public/visuals/silent.mp4 \
    && chown -R 1000:1000 fixtures/public/visuals
RUN ln -s /state/.astro /app/.astro \
    && ln -s /state/.astro-cache /app/node_modules/.astro \
    && test -x node_modules/.bin/astro \
    && test -r package-lock.json \
    && test -x /usr/local/bin/d2 \
    && test -r /opt/plantuml.jar
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["node", "/app/scripts/healthcheck.mjs"]
USER 1000:1000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
