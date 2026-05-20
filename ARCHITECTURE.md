# klight — Architecture

## Design Principles

### 1. Environments are namespaces, not VMs

Enterprise platforms use dedicated VMs ("boxes") provisioned from a warm pool. For startups, the overhead of managing VM fleets is prohibitive. klight maps one environment to one Kubernetes namespace.

Benefits:
- Near-instant creation (`kubectl create namespace` takes < 1s)
- No cloud cost when not in use
- RBAC per namespace = isolation without VM isolation
- All environments in one cluster = cheaper than N separate clusters

Trade-off: less isolation than dedicated VMs (shared kernel, shared cluster network). Acceptable for dev/staging; for production use separate clusters.

### 2. Kustomize base + overlay

Every resource follows:
```
manifests/services/my-service/
├── base/                    # Shared across all environments
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
└── overlays/
    ├── dev/                 # All dev/PR environments
    │   ├── kustomization.yaml
    │   └── config.env
    └── staging/             # Staging overrides
        ├── kustomization.yaml
        └── config.env
```

This is the exact same pattern as `sofi-kubernetes/deployments/{service}/base` + `overlays/dev`. It scales cleanly from 5 to 500 services.

### 3. Sentinel init container for dependency ordering

Kubernetes does not provide native pod ordering. When `my-api` depends on `postgres` and `redis`, those must be ready before `my-api` starts — otherwise it crashes, CrashLoopBackOffs pile up.

The `sentinel` init container solves this identically to SoFi's internal sentinel:

```yaml
initContainers:
- name: sentinel
  image: your-registry/klight-sentinel:latest
  env:
  - name: STARTUP_DEPENDENCIES
    value: "postgres:5432 redis:6379"
```

`sentinel` polls each dependency's TCP port (or HTTP `/health` endpoint) and blocks until all are ready. This eliminates startup race conditions.

### 4. Configuration via Kustomize ConfigMaps

Config is never baked into images. It flows through ConfigMaps generated from `.env` files:

```
env/config/global.env          → klight-global-config ConfigMap
services/my-api/overlays/dev/config.env  → my-api-config ConfigMap (merged with global)
```

Services consume config via `envFrom.configMapRef` — same approach as Kraken.

### 5. Secrets: Vault in dev, External Secrets Operator in prod

- **Development**: HashiCorp Vault deployed as a StatefulSet in each environment namespace. Dev credentials only. Vault starts empty; CI seeds it per environment.
- **Production**: External Secrets Operator (ESO) pulls from AWS Secrets Manager, GCP Secret Manager, or Vault. Secrets are never in Git.

Both integrate via the same environment variable interface — switching from Vault to ESO is transparent to application code.

### 6. Databases as StatefulSets with migration Jobs

Each database is a StatefulSet with:
- A PersistentVolumeClaim for data
- A headless Service for DNS resolution (`postgres.env-alice.svc.cluster.local`)
- A migration Job that waits for the DB (via sentinel), then runs Flyway/Liquibase/custom SQL

```
jobs/my-api-dbmigrate/
└── base/
    ├── job.yaml        # K8s Job: runs migration container
    └── kustomization.yaml
```

### 7. Service profiles for startup ordering

A "profile" is a Kubernetes Job that declares which services must be healthy before it completes. When you run `klight profile up backend`, it:

1. Deploys all services in the profile
2. Runs the profile job (which uses sentinel to wait for all of them)
3. Exits when the entire profile is healthy

This mirrors SoFi's `money-stack-startup` job pattern exactly.

---

## Component Diagram

```
                        ┌─────────────────────────────────────┐
                        │         Kubernetes Cluster          │
                        │                                     │
  ┌──────────────────┐  │  ┌──────────────────────────────┐   │
  │   Developer /    │  │  │   namespace: env-alice        │   │
  │   GitHub PR      │  │  │                               │   │
  └────────┬─────────┘  │  │  ┌──────────┐  ┌──────────┐  │   │
           │            │  │  │  my-api  │  │  my-web  │  │   │
    klight CLI          │  │  │ (Deployment) │ (Deployment) │  │
    or GH Actions       │  │  └─────┬────┘  └──────────┘  │   │
           │            │  │        │ reads config          │   │
           │ kubectl     │  │  ┌─────┴────────────────────┐ │   │
           │ apply -k    │  │  │     klight-global-config  │ │   │
           └────────────►│  │  │     my-api-config         │ │   │
                        │  │  └──────────────────────────-┘ │   │
                        │  │                               │   │
                        │  │  ┌──────────┐  ┌──────────┐  │   │
                        │  │  │ postgres │  │  redis   │  │   │
                        │  │  │(StatefulSet)│(StatefulSet)│  │   │
                        │  │  └──────────┘  └──────────┘  │   │
                        │  │                               │   │
                        │  │  ┌──────────────────────────┐ │   │
                        │  │  │  vault (StatefulSet)     │ │   │
                        │  │  │  or External Secrets Op.  │ │   │
                        │  │  └──────────────────────────┘ │   │
                        │  └──────────────────────────────┘   │
                        │                                     │
                        │  ┌──────────────────────────────┐   │
                        │  │   namespace: env-pr-456       │   │
                        │  │   (identical structure)       │   │
                        │  └──────────────────────────────┘   │
                        └─────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Manifest format | Kustomize | Same as full Kraken; no Helm templating complexity for most cases |
| Dependency ordering | Custom sentinel (bash + curl/nc) | Simple, debuggable, no external dependency |
| CLI | Python + Typer | Fast to iterate, familiar to platform teams |
| Secrets (dev) | HashiCorp Vault | Parity with full Kraken; free open source |
| Secrets (prod) | External Secrets Operator | Cloud-native, works with AWS/GCP/Azure |
| CI/CD | GitHub Actions | Universal for startups |
| DB migrations | Any (Flyway, Liquibase, custom) | Agnostic — uses K8s Job pattern |

---

## What we deliberately did NOT include

- **Consul service discovery**: CoreDNS handles service DNS natively in K8s. Consul adds operational burden not justified for < 50 services.
- **Istio service mesh**: Add it yourself if you need mTLS or advanced traffic management. Kustomize overlays make it a one-label change per deployment.
- **Pool-based provisioning**: Pre-warming namespaces provides marginal benefit; namespace creation is already < 1 second.
- **Sunbot-style GitOps bot**: GitHub Actions merge jobs + `kubectl apply -k` cover 95% of the use case at zero maintenance cost.
- **envconsul**: Kustomize ConfigMaps are sufficient. envconsul's runtime config-change capability is complex to operate and rarely needed.
