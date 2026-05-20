# Secrets & Config

## Two layers of configuration

```
manifests/env/config/global.env   → klight-global-config ConfigMap (shared by all services)
klight.yaml env: section          → {service}-config ConfigMap (service-specific)
```

Service-specific keys override global keys with the same name.

## Global config (safe to commit)

```bash
# manifests/env/config/global.env
GLOBAL_POSTGRES_HOST=postgres
GLOBAL_REDIS_HOST=redis
GLOBAL_KAFKA_BOOTSTRAP=kafka:9092
GLOBAL_LOG_LEVEL=INFO
GLOBAL_APP_ENV=dev
```

## Service config (from klight.yaml)

```yaml
# klight.yaml
env:
  MY_SERVICE_PORT: "8080"
  MY_DB_NAME: my_service_db
  # Override global for this service only:
  GLOBAL_LOG_LEVEL: DEBUG
```

## Secrets (never in Git)

klight creates a `klight-global-secrets` Secret from `manifests/env/secrets/global.env` (gitignored).

```bash
cp manifests/env/secrets/global.env.example manifests/env/secrets/global.env
# Edit: set real dev values (never commit this file)
```

The `.gitignore` already excludes `manifests/env/secrets/global.env`.

## Auto-provided env vars from catalog

When you declare `needs: [postgres]`, klight automatically injects:
- `GLOBAL_POSTGRES_HOST=postgres`
- `GLOBAL_POSTGRES_PORT=5432`

These come from the catalog's `provides:` section. You don't need to list them in `env:` unless you want to override them or your code reads a different variable name.

## For CI / PR environments

Seed secrets from CI environment variables:
```bash
klight vault seed --env pr-123 --from-ci-env POSTGRES_PASSWORD JWT_SECRET STRIPE_KEY
```

Or create the K8s Secret directly:
```bash
kubectl -n env-pr-123 create secret generic klight-global-secrets \
  --from-literal=POSTGRES_PASSWORD=${{ secrets.DEV_DB_PASS }}
```

## External Secrets Operator (production)

For production, use ESO to sync from AWS Secrets Manager, GCP Secret Manager, or Vault:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: klight-global-secrets
spec:
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: klight-global-secrets
  dataFrom:
  - extract:
      key: mycompany/dev/klight-global
```
