#!/bin/sh
# sentinel — wait for upstream dependencies before pod starts
# Works with busybox: nc (TCP), wget (HTTP), /bin/sh
set -e

TIMEOUT=${SENTINEL_TIMEOUT:-120}
INTERVAL=${SENTINEL_INTERVAL:-2}

if [ -n "${RUNTIME_DEPENDENCIES:-}" ]; then
  echo "[sentinel] Runtime deps (non-blocking): ${RUNTIME_DEPENDENCIES}"
fi

if [ -z "${STARTUP_DEPENDENCIES:-}" ]; then
  echo "[sentinel] No STARTUP_DEPENDENCIES, proceeding"
  exit 0
fi

wait_tcp() {
  host="$1" port="$2" elapsed=0
  echo "[sentinel] Waiting for TCP ${host}:${port}..."
  until nc -z "$host" "$port" 2>/dev/null; do
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
      echo "[sentinel] TIMEOUT: ${host}:${port} not reachable after ${TIMEOUT}s"
      exit 1
    fi
  done
  echo "[sentinel] ${host}:${port} ready"
}

wait_http() {
  host="$1" port="$2" path="$3" elapsed=0
  url="http://${host}:${port}${path}"
  echo "[sentinel] Waiting for HTTP ${url}..."
  until wget -q --spider "$url" 2>/dev/null; do
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
      echo "[sentinel] TIMEOUT: ${url} not responding after ${TIMEOUT}s"
      exit 1
    fi
  done
  echo "[sentinel] ${url} ready"
}

for dep in $STARTUP_DEPENDENCIES; do
  host="${dep%%:*}"
  rest="${dep#*:}"
  port="${rest%%/*}"
  path="${rest#$port}"
  if [ -z "$path" ]; then
    wait_tcp "$host" "$port"
  else
    wait_http "$host" "$port" "$path"
  fi
done

echo "[sentinel] All dependencies ready."
