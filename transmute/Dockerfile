# syntax=docker/dockerfile:1.7
# Drop this rebuild when an upstream release includes Pillow's decoder fixes:
# https://github.com/python-pillow/Pillow/security/advisories/GHSA-8g5g-8vmr-9782
FROM ghcr.io/transmute-app/transmute:v2.1.1@sha256:87b669d835d9e68bdbc4082ab061cb361cd3ecee69c14ccfa9a3814d326b6707
LABEL org.opencontainers.image.source="https://github.com/alxleo/docker-images"

COPY requirements.txt /tmp/transmute-security-requirements.txt
# conftest:exempt=user_required -- preserve upstream startup identity; deployments own their UID
RUN pip install --no-cache-dir --no-deps -r /tmp/transmute-security-requirements.txt \
    && rm /tmp/transmute-security-requirements.txt
