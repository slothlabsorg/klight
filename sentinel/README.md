# sentinel

Lightweight init container that blocks a Kubernetes pod from starting until its upstream dependencies are healthy.

## Build

```bash
docker build -t your-registry/klight-sentinel:latest .
docker push your-registry/klight-sentinel:latest
```

## Usage

```yaml
initContainers:
- name: sentinel
  image: your-registry/klight-sentinel:latest
  env:
  - name: STARTUP_DEPENDENCIES
    value: "postgres:5432 redis:6379 auth-service:8080/actuator/health"
  - name: SENTINEL_TIMEOUT
    value: "120"
```

## Dependency formats

| Format | Example | Check type |
|---|---|---|
| `host:port` | `postgres:5432` | TCP connection |
| `host:port/path` | `auth-service:8080/actuator/health` | HTTP GET (expects 2xx) |

Multiple dependencies are space-separated.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `STARTUP_DEPENDENCIES` | (none) | Space-separated dependencies; pod blocks until all ready |
| `RUNTIME_DEPENDENCIES` | (none) | Logged but non-blocking |
| `SENTINEL_TIMEOUT` | `120` | Seconds before giving up |
| `SENTINEL_INTERVAL` | `2` | Polling interval in seconds |

## Why not use `wait-for-it.sh`?

`wait-for-it.sh` checks a single TCP endpoint. Sentinel handles:
- Multiple dependencies in one container (no need for chained init containers)
- HTTP health check paths (for services where TCP ready ≠ app ready)
- Configurable timeout and interval via env vars
- Clear structured logging

## Image size

The image is based on `alpine:3.19` with `bash`, `curl`, and `netcat-openbsd` only. Final size ~12MB.
