# syntax=docker/dockerfile:1.28
# Upstream: https://github.com/transmute-app/transmute/tree/v2.1.1
# Preserve filenames/layout and use household quality and retention defaults.
# Drop each patch when its behavior is provided by upstream.
FROM --platform=$BUILDPLATFORM ghcr.io/alxleo/base-images/node:26-alpine AS frontend
# hadolint ignore=DL3018
RUN apk add --no-cache git
RUN git clone --branch v2.1.1 --depth 1 --filter=blob:none --sparse \
      https://github.com/transmute-app/transmute.git /src \
    && test "$(git -C /src rev-parse HEAD)" = 7de1265fbfbbfd073c5c9a65ed1f7e45bc3ca50c \
    && git -C /src sparse-checkout set frontend backend/converters backend/background backend/db backend/services backend/api/routes
WORKDIR /src
COPY download-filename.patch fixed-layout-epub.patch retention-quality.patch /tmp/
RUN git apply /tmp/download-filename.patch /tmp/fixed-layout-epub.patch /tmp/retention-quality.patch
WORKDIR /src/frontend
COPY download.test.ts src/utils/download.test.ts
RUN npm ci && npm test -- src/utils/download.test.ts && npm run build

# KindleUnpack owns KF8 reconstruction, including fixed-layout EPUB3 viewports.
ADD https://github.com/kevinhendricks/KindleUnpack.git#bf0ca6ece4e73494625e7950be3e259b6260774c /kindleunpack

# Drop the dependency rebuild when upstream includes the decoder and trust-store fixes:
# https://github.com/python-pillow/Pillow/security/advisories/GHSA-8g5g-8vmr-9782
FROM ghcr.io/transmute-app/transmute:v2.1.1@sha256:87b669d835d9e68bdbc4082ab061cb361cd3ecee69c14ccfa9a3814d326b6707
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

COPY requirements.txt /tmp/transmute-security-requirements.txt
# conftest:exempt=user_required -- preserve upstream startup identity; deployments own their UID
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends --yes --only-upgrade libbrotli1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /tmp/transmute-security-requirements.txt \
    && rm /tmp/transmute-security-requirements.txt

COPY --from=frontend /src/frontend/dist /app/frontend/dist
COPY --from=frontend /src/backend/converters/calibre_convert.py /app/backend/converters/calibre_convert.py
COPY --from=frontend /src/backend/background/cleanup.py /app/backend/background/cleanup.py
COPY --from=frontend /src/backend/db/settings_db.py /app/backend/db/settings_db.py
COPY --from=frontend /src/backend/db/file_db.py /app/backend/db/file_db.py
COPY --from=frontend /src/backend/services/conversion_service.py /app/backend/services/conversion_service.py
COPY --from=frontend /src/backend/api/routes/jobs.py /app/backend/api/routes/jobs.py
COPY --from=frontend /src/backend/api/routes/compression_jobs.py /app/backend/api/routes/compression_jobs.py
# The pinned runtime is Python 3.13; install in its native module search path.
COPY --from=frontend /kindleunpack/lib /usr/local/lib/python3.13/site-packages/kindleunpack
COPY --from=frontend /kindleunpack/COPYING.txt /app/licenses/KindleUnpack-COPYING.txt
