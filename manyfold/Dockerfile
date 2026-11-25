FROM ghcr.io/manyfold3d/manyfold-solo:0.154.4@sha256:ecffe1f17f940646e76a089578e0220e51a9e753f0ef31c68638cbd505880916
LABEL org.opencontainers.image.source=https://github.com/alxleo/docker-images

USER 0:0
COPY apply_fixes.rb /tmp/apply_fixes.rb
RUN ruby /tmp/apply_fixes.rb && rm /tmp/apply_fixes.rb \
    && chown 1000:1000 /usr/src/app/tmp /usr/src/app/log
# user-has-group:exempt=1000 -- manyfold-solo ships its app user at uid 1000
# (the chown targets above are its runtime dirs); the root USER exists only to
# apply the fixups in apply_fixes.rb.
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s CMD ["ruby", "-rnet/http", "-e", "exit(Net::HTTP.get_response(URI(\"http://127.0.0.1:#{ENV.fetch(\"PORT\", \"3214\")}/health\")).code == \"200\" ? 0 : 1)"]
