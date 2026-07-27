#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: runtime-smoke.sh IMAGE_REF" >&2
    exit 2
fi

image_ref=$1
state_dir=$(mktemp -d)
root_state_dir="${state_dir}-root"
container_name="docs-hub-smoke-$$"
root_container_name="${container_name}-root"

cleanup() {
    docker rm -f "$container_name" >/dev/null 2>&1 || true
    docker rm -f "$root_container_name" >/dev/null 2>&1 || true
    # Linux bind mounts preserve the container UID on generated files. Make
    # both disposable state trees removable by an unprivileged CI runner.
    docker run --rm --user 0:0 --volume "$state_dir:/state" \
        --entrypoint chmod "$image_ref" -R a+rwx /state >/dev/null 2>&1 || true
    docker run --rm --user 0:0 --volume "$root_state_dir:/state" \
        --entrypoint chmod "$image_ref" -R a+rwx /state >/dev/null 2>&1 || true
    rm -rf "$state_dir" "$root_state_dir"
}
trap cleanup EXIT INT TERM

mkdir -p "$state_dir/releases/smoke"
printf '%s\n' '<!doctype html><title>Docs Hub smoke</title>' >"$state_dir/releases/smoke/index.html"
ln -s releases/smoke "$state_dir/current"
mkdir -p "$state_dir/.astro" "$state_dir/.astro-cache"
ln -s /app/node_modules "$state_dir/node_modules"
chmod -R a+rwx "$state_dir"

docker run --detach \
    --name "$container_name" \
    --publish 127.0.0.1::8080 \
    --env DOCS_HUB_MODE=assets \
    --volume "$state_dir:/state" \
    "$image_ref" >/dev/null

port=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8080/tcp") 0).HostPort}}' "$container_name")
attempt=0
until curl --fail --silent --show-error "http://127.0.0.1:${port}/healthz" >/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 20 ]; then
        docker logs "$container_name" >&2
        exit 1
    fi
    sleep 1
done

curl --fail --silent --show-error "http://127.0.0.1:${port}/" | grep -q "Docs Hub smoke"
docker exec "$container_name" node /app/scripts/healthcheck.mjs
docker exec "$container_name" sh -c 'test "$(id -u)" = 1000 && test "$(id -g)" = 1000'
docker exec "$container_name" d2 --version >/dev/null
docker exec "$container_name" dot -V >/dev/null 2>&1
docker exec "$container_name" java -jar /opt/plantuml.jar -version >/dev/null

docker run --rm \
    --read-only \
    --tmpfs /tmp:exec,mode=1777 \
    --user 1000:1000 \
    --workdir /app \
    --env DOCS_HUB_CONTENT_ROOT=/app/fixtures/content \
    --env DOCS_HUB_PUBLIC_ROOT=/app/fixtures/public \
    --volume "$state_dir:/state" \
    --entrypoint /app/node_modules/.bin/astro \
    "$image_ref" build --outDir /state/read-only-build >/dev/null
test -f "$state_dir/read-only-build/index.html"

mkdir -p "$root_state_dir/releases/smoke"
printf '%s\n' '<!doctype html><title>Docs Hub root-start smoke</title>' >"$root_state_dir/releases/smoke/index.html"
ln -s releases/smoke "$root_state_dir/current"
chmod 700 "$root_state_dir"

docker run --detach \
    --name "$root_container_name" \
    --user 0:0 \
    --env DOCS_HUB_MODE=assets \
    --volume "$root_state_dir:/state" \
    "$image_ref" >/dev/null

attempt=0
until docker exec "$root_container_name" node /app/scripts/healthcheck.mjs >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 20 ]; then
        docker logs "$root_container_name" >&2
        exit 1
    fi
    sleep 1
done

docker exec "$root_container_name" awk '
  /^Uid:/ {
    if ($2 != 1000 || $3 != 1000 || $4 != 1000 || $5 != 1000) exit 1
    uid = 1
  }
  /^Gid:/ {
    if ($2 != 1000 || $3 != 1000 || $4 != 1000 || $5 != 1000) exit 1
    gid = 1
  }
  END {
    if (!uid || !gid) exit 1
  }
' /proc/1/status
docker exec "$root_container_name" stat -c '%u:%g' /state | grep -q '^1000:1000$'
