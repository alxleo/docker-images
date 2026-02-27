# cAdvisor v0.56.2 — custom build for Docker 29+ compatibility
#
# Why: ghcr.io/google/cadvisor stuck at v0.53.0 which crashes with Docker 29's
# restructured storage paths. v0.56.2 fixes this but isn't published as a
# container image.
#
# Simplified from upstream deploy/Dockerfile — strips libpfm4, ipmctl, and
# other extras not needed for self-hosted container metrics.
#
# Remove when: ghcr.io publishes v0.57+ (or any >= v0.56.2)

FROM golang:1.24-alpine AS build

RUN apk --no-cache add bash build-base device-mapper findutils git \
                       libc6-compat linux-headers pkgconfig thin-provisioning-tools zfs

WORKDIR /src
RUN git clone --branch v0.56.2 --depth 1 https://github.com/google/cadvisor.git .

# Cache Go module downloads
RUN go mod download && cd cmd && go mod download

# Build using upstream build script (outputs to _output/cadvisor)
RUN GO_FLAGS="-tags=netgo" ./build/build.sh

FROM alpine:3.21
RUN apk --no-cache add libc6-compat device-mapper findutils thin-provisioning-tools && \
    rm -rf /var/cache/apk/*
COPY --from=build /src/_output/cadvisor /usr/bin/cadvisor

EXPOSE 8080
ENTRYPOINT ["/usr/bin/cadvisor"]
