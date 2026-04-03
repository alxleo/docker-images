# cAdvisor v0.56.2 — custom build for Docker 29+ compatibility
#
# Why: ghcr.io/google/cadvisor stuck at v0.53.0 which crashes with Docker 29's
# restructured storage paths. v0.56.2 fixes this but isn't published as a
# container image.
#
# Simplified from upstream deploy/Dockerfile — strips libpfm4, ipmctl, and
# other extras not needed for basic container metrics.
#
# Remove when: ghcr.io publishes v0.57+ (or any >= v0.56.2)

FROM ghcr.io/alxleo/base-images/golang:1.25-alpine AS build

ARG CADVISOR_VERSION=v0.56.2

RUN apk --no-cache add bash build-base device-mapper findutils git \
                       libc6-compat linux-headers pkgconfig thin-provisioning-tools zfs

WORKDIR /src
RUN git clone --branch ${CADVISOR_VERSION} --depth 1 https://github.com/google/cadvisor.git .

# Cache Go module downloads
RUN go mod download
WORKDIR /src/cmd
RUN go mod download
WORKDIR /src

# Build using upstream build script (outputs to _output/cadvisor)
RUN GO_FLAGS="-tags=netgo" ./build/build.sh

# conftest:exempt=user_required -- reads /sys/fs/cgroup and /proc
FROM ghcr.io/alxleo/base-images/alpine:3.23
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images
RUN apk --no-cache upgrade && \
    apk --no-cache add libc6-compat device-mapper findutils thin-provisioning-tools && \
    rm -rf /var/cache/apk/*
COPY --from=build /src/_output/cadvisor /usr/bin/cadvisor

EXPOSE 8080

COPY --from=ghcr.io/tarampampam/microcheck:1 /bin/httpcheck /bin/httpcheck

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["/bin/httpcheck", "http://localhost:8080/healthz"]

ENTRYPOINT ["/usr/bin/cadvisor"]
