# syntax=docker/dockerfile:1.28
FROM ghcr.io/alxleo/base-images/node:26-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts && npm cache clean --force

FROM ghcr.io/alxleo/base-images/alpine:3.23 AS renderers
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]
ARG TARGETARCH
# renovate: depName=terrastruct/d2
ARG D2_VERSION=v0.9.0
ARG D2_CHECKSUMS_SHA256=0e6997fa55b922741e32cb29aaf8a985b4a5d7b2caa85b08bfd0ef0607a48a71
# renovate: depName=plantuml/plantuml
ARG PLANTUML_VERSION=v1.2026.9
ARG PLANTUML_SHA256=aa4a1d06f8911c4b842beff4828dd955be431692b631a312d04c0e9fab9581de
RUN apk add --no-cache ca-certificates curl \
    && case "${TARGETARCH}" in \
         amd64|arm64) ;; \
         *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && d2_release="https://github.com/terrastruct/d2/releases/download/${D2_VERSION}" \
    && d2_asset="d2-${D2_VERSION}-linux-${TARGETARCH}.tar.gz" \
    && curl -fsSL -o /tmp/d2-checksums "${d2_release}/SHA256SUMS" \
    && echo "${D2_CHECKSUMS_SHA256}  /tmp/d2-checksums" | sha256sum -c - \
    && curl -fsSL -o /tmp/d2.tar.gz "${d2_release}/${d2_asset}" \
    && awk -v asset="${d2_asset}" '$2 == asset { print $1 "  /tmp/d2.tar.gz" }' /tmp/d2-checksums | sha256sum -c - \
    && tar -xzf /tmp/d2.tar.gz -C /tmp \
    && install -m 0755 "/tmp/d2-${D2_VERSION}/bin/d2" /usr/local/bin/d2 \
    && curl -fsSL -o /opt/plantuml.jar \
       "https://github.com/plantuml/plantuml/releases/download/${PLANTUML_VERSION}/plantuml.jar" \
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
COPY --chown=1000:1000 astro.config.mjs tsconfig.json package.json package-lock.json ./
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
