# Service Dependencies

## The problem

Without dependency ordering, `my-api` starts before `postgres` is ready → crash → CrashLoopBackOff for 2+ minutes.

## Sentinel init container

klight's sentinel blocks a pod from starting until upstream dependencies are healthy.

**In klight.yaml:**
```yaml
depends:
  - postgres:5432                    # TCP check
  - kafka:9092                       # TCP check
  - inventory-api:8081/health        # HTTP GET (expects 2xx)
```

klight sets `STARTUP_DEPENDENCIES` in the sentinel init container automatically.

**Sentinel image:** `busybox:stable-uclibc` with a bash script. Polls TCP or HTTP. Zero network dependencies at build time.

**Note:** The service developer never writes sentinel. klight adds it:
- For klight-generated manifests: baked into the Deployment
- For existing `deploy/` manifests: injected via `kubectl patch` after apply

## Sentinel env vars

| Var | Default | Description |
|---|---|---|
| `STARTUP_DEPENDENCIES` | set by klight | Space-separated `host:port` or `host:port/path` |
| `SENTINEL_TIMEOUT` | 180 | Seconds before giving up |
| `SENTINEL_INTERVAL` | 2 | Polling interval in seconds |

## `needs:` vs `depends:`

- `needs: [postgres, kafka]` → spins up infra AND adds `postgres:5432 kafka:9092` to sentinel
- `depends: [other-service:8081/health]` → adds a service-to-service dependency to sentinel

Together:
```yaml
needs: [postgres, kafka]
depends:
  - inventory-api:8081/health   # waits for another service
```

Sentinel STARTUP_DEPENDENCIES: `postgres:5432 kafka:9092 inventory-api:8081/health`

## Debugging

```bash
# Pod stuck in Init:0/1
kubectl -n env-alice logs <pod-name> -c sentinel
# Shows exactly what's being waited for

klight unready --env alice
# Shows broken services with a fix hint
```
