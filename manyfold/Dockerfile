FROM ghcr.io/manyfold3d/manyfold-solo:0.154.1@sha256:f1b7784fb63aec500fca61081d3f970948fc652ad16ecdc5d57cd3c0c925127f
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

USER 0:0
COPY apply_fixes.rb /tmp/apply_fixes.rb
RUN ruby /tmp/apply_fixes.rb && rm /tmp/apply_fixes.rb \
    && chown 1000:1000 /usr/src/app/tmp /usr/src/app/log
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s CMD ["ruby", "-rnet/http", "-e", "exit(Net::HTTP.get_response(URI(\"http://127.0.0.1:#{ENV.fetch(\"PORT\", \"3214\")}/health\")).code == \"200\" ? 0 : 1)"]
