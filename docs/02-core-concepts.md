# Core Concepts

## Environment

A Kubernetes **namespace** with a lifecycle. Contains a complete, isolated copy of your application stack.

```
namespace: env-alice
  pods:     my-api, my-worker, kafka-0, postgres-0
  configmaps: klight-global-config, my-api-config
  secrets:  klight-global-secrets
```

Naming: `env-alice` (dev), `env-pr-123` (PR), `env-staging` (persistent).

## klight.yaml

The service contract. Commit it to your service repo alongside the Dockerfile.

```yaml
name: my-api        # K8s service name, DNS hostname within namespace
port: 8080          # HTTP port
health: /health     # liveness/readiness probe path
needs: [postgres, kafka]   # infra to spin up
env:
  DB_HOST: postgres        # exact env var names your code reads
  KAFKA_BOOTSTRAP: kafka:9092
migration:
  command: ["python", "-m", "app.migrate"]
```

VS Code autocomplete: add `# yaml-language-server: $schema=https://slothlabsorg.github.io/klight/schema/klight.yaml.json` at the top.

## Infra Catalog

`needs:` entries reference the catalog (`klight-catalog.yaml`). klight ships with postgres, redis, kafka, localstack, mysql, mongodb, ollama, chromadb, elasticsearch, rabbitmq, vault. Add custom entries in your project's `klight-catalog.yaml` without touching klight's source.

Each catalog entry provides env vars automatically. `needs: [postgres]` injects `GLOBAL_POSTGRES_HOST=postgres` for all services — no manual env var needed.

## Sentinel

Init container that blocks a pod from starting until its upstream dependencies are healthy (TCP or HTTP). Prevents CrashLoopBackOff from race conditions.

The service developer never writes sentinel. When using klight-generated manifests, it's added automatically. When using existing `deploy/` manifests, klight injects it via `kubectl patch` after applying.

```
STARTUP_DEPENDENCIES="postgres:5432 kafka:9092 inventory-api:8081/health"
```

## Profile

Named group of services started together. Used in DevOps-managed infra repos. Profiles support `includes:` to compose:

```yaml
# vertical2.yaml
name: vertical2
includes: [core]           # starts core services first
services:
  - name: vertical2-api    # adds vertical2-specific services
```

## manifest: field

When a service already has K8s manifests (`deploy/` folder or separate infra repo):

```yaml
manifest: ./deploy/overlays/dev   # klight uses these, doesn't generate new ones
needs: [postgres, kafka]          # klight still manages infra startup
```

## build: field

For non-standard builds (Gradle Jib, SBT, Quarkus, monorepos):

```yaml
build:
  command: ./gradlew banking:jib --image=banking:local
  context: ../    # monorepo root
```

## Two targets: local and remote

```bash
klight use local    # kubectl context → klight-demo (minikube)
klight use remote   # kubectl context → company-dev cluster
```

Configured in `klight.toml` at the infra repo root.
