FROM ekofr/pihole-exporter:v1.2.0 AS upstream

FROM ghcr.io/alxleo/base-images/alpine:3.23
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

RUN apk add --no-cache ca-certificates

COPY --from=upstream /root/pihole-exporter /usr/local/bin/pihole-exporter
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /usr/local/bin/pihole-exporter /entrypoint.sh

EXPOSE 9617

ENTRYPOINT ["/entrypoint.sh"]
CMD []
