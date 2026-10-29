# syntax=docker/dockerfile:1.7
# Upstream: https://github.com/transmute-app/transmute/tree/v2.1.1
# Keep metadata filenames instead of misparsing UTF-8 Content-Disposition.
# Drop the frontend patch when upstream download.ts uses the supplied filename.
FROM --platform=$BUILDPLATFORM ghcr.io/alxleo/base-images/node:26-alpine AS frontend
# hadolint ignore=DL3018
RUN apk add --no-cache git
RUN git clone --branch v2.1.1 --depth 1 --filter=blob:none --sparse \
      https://github.com/transmute-app/transmute.git /src \
    && cd /src \
    && test "$(git rev-parse HEAD)" = 7de1265fbfbbfd073c5c9a65ed1f7e45bc3ca50c \
    && git sparse-checkout set frontend
WORKDIR /src
COPY download-filename.patch /tmp/download-filename.patch
RUN git apply /tmp/download-filename.patch
WORKDIR /src/frontend
COPY download.test.ts src/utils/download.test.ts
RUN npm ci && npm test -- src/utils/download.test.ts && npm run build

# Drop the dependency rebuild when an upstream release includes Pillow's decoder fixes:
# https://github.com/python-pillow/Pillow/security/advisories/GHSA-8g5g-8vmr-9782
FROM ghcr.io/transmute-app/transmute:v2.1.1@sha256:87b669d835d9e68bdbc4082ab061cb361cd3ecee69c14ccfa9a3814d326b6707
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

COPY requirements.txt /tmp/transmute-security-requirements.txt
# conftest:exempt=user_required -- preserve upstream startup identity; deployments own their UID
RUN pip install --no-cache-dir --no-deps -r /tmp/transmute-security-requirements.txt \
    && rm /tmp/transmute-security-requirements.txt

COPY --from=frontend /src/frontend/dist /app/frontend/dist
