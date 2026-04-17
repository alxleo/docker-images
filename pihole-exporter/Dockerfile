ARG PIHOLE_EXPORTER_VERSION=v1.2.0

FROM ghcr.io/alxleo/base-images/golang:1.25-alpine AS build
ARG PIHOLE_EXPORTER_VERSION
ENV CGO_ENABLED=0 \
    GOBIN=/out

RUN go install github.com/eko/pihole-exporter@${PIHOLE_EXPORTER_VERSION}

FROM ghcr.io/alxleo/base-images/alpine:3.23
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

RUN apk add --no-cache ca-certificates

COPY --from=build /out/pihole-exporter /usr/local/bin/pihole-exporter
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /usr/local/bin/pihole-exporter /entrypoint.sh

COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

EXPOSE 9617

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:9617/metrics"]

# Create a matching uid=1000/gid=1000 app user. The base alpine:3.23 doesn't
# ship one (unlike node:24-alpine), so USER 1000 was running with gid=0
# (root) and couldn't read Docker secrets group-owned by gid=1000. Same
# pattern as the mcp-substack fix in #143.
RUN addgroup -g 1000 -S app \
    && adduser -u 1000 -G app -S -D -s /sbin/nologin app
USER app

ENTRYPOINT ["/entrypoint.sh"]
CMD []
