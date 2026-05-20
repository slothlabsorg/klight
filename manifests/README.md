# Manifests

Kustomize templates for all Kubernetes resources.

## Structure

```
manifests/
├── env/
│   ├── config/
│   │   ├── global.env           Global non-sensitive config (commit this)
│   │   └── kustomization.yaml   Generates klight-global-config ConfigMap
│   └── secrets/
│       ├── global.env.example   Example secrets file (commit this)
│       ├── global.env           Real secrets file (GITIGNORED)
│       └── kustomization.yaml   Generates klight-global-secrets Secret
│
├── infrastructure/
│   ├── postgres/                PostgreSQL 16 StatefulSet
│   ├── redis/                   Redis 7 StatefulSet
│   └── vault/                   HashiCorp Vault StatefulSet
│
├── services/
│   └── _template/               Copy this for each new service
│
└── jobs/
    └── _template/               Copy this for each DB migration job
```

## Adding a new service

```bash
cp -r manifests/services/_template manifests/services/my-service
# Edit files, replacing REPLACE_ME_SERVICE_NAME with my-service
```

## Applying manifests

```bash
# Apply a service to an environment
kubectl apply -k manifests/services/my-service/overlays/dev -n env-alice

# Apply infrastructure
kubectl apply -k manifests/infrastructure/postgres/base -n env-alice

# Apply global config
kubectl apply -k manifests/env/config -n env-alice
```

## Adding a new overlay

```bash
mkdir manifests/services/my-service/overlays/staging
# Create kustomization.yaml and config.env
```
