"""Native Rails API and stored bytes in the exact built application image."""

from pathlib import Path


def test_native_curation_and_upload_contract(image_ref, docker):
    source = Path(__file__).with_name("acceptance.rb").resolve()
    output = docker.run(
        "--network", "none",
        "--mount", f"type=bind,src={source},dst=/tmp/acceptance.rb,readonly",
        "-e", "DATABASE_URL=sqlite3:/tmp/acceptance.sqlite3",
        "-e", "REDIS_URL=unix:///tmp/acceptance-redis.sock",
        "-e", "RAILS_ENV=production",
        "-e", "MULTIUSER=enabled",
        "-e", "PUBLIC_HOSTNAME=localhost",
        "-e", "HTTPS_ONLY=disabled",
        "-e", "SECRET_KEY_BASE=acceptance-only-not-a-deployment-key",
        "--entrypoint", "/bin/sh", image_ref, "-ec",
        "redis-server --port 0 --unixsocket /tmp/acceptance-redis.sock --daemonize yes; "
        "bundle exec rails db:prepare; "
        "bundle exec rails runner /tmp/acceptance.rb seed; "
        "bundle exec rails runner /tmp/acceptance.rb",
    )
    assert "collision preservation passed" in output
