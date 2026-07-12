# Custom Infrastructure Catalog

klight ships with a built-in catalog (`postgres`, `kafka`, `redis`, `mongodb`, `rabbitmq`, `localstack`, `elasticsearch`). When a service declares `needs:` entries that are **not** in the built-in catalog, klight fails with a clear error — or the Setup Wizard flags them during repo scan.

This guide explains how to add custom infra entries without modifying klight source code.

---

## When you need a custom catalog entry

| Situation | Solution |
|-----------|----------|
| One shared postgres per namespace is enough | Rename `needs: [postgres-store]` → `needs: [postgres]` |
| Multiple postgres instances (different DBs/credentials) | Add `postgres-store`, `postgres-inventory`, etc. to catalog |
| Non-standard image or port | Custom catalog entry with `manifest:` |
| Company-specific infra (Vault, Ollama, ChromaDB) | Custom catalog entry |

---

## Step 1 — Create `klight-catalog.yaml`

Place at your project or infra repo root:

```yaml
# klight-catalog.yaml
infra:
  postgres-store:
    description: "PostgreSQL 16 for store-api"
    image: postgres:16-alpine
    port: 5432
    manifest: infrastructure/postgres-store/base
    provides:
      GLOBAL_POSTGRES_STORE_HOST: postgres-store
      GLOBAL_POSTGRES_STORE_PORT: "5432"

  postgres-inventory:
    description: "PostgreSQL 16 for inventory-api"
    image: postgres:16-alpine
    port: 5432
    manifest: infrastructure/postgres-inventory/base
    provides:
      GLOBAL_POSTGRES_INVENTORY_HOST: postgres-inventory
      GLOBAL_POSTGRES_INVENTORY_PORT: "5432"
```

Catalog loading order (later wins):

1. Built-in defaults (in klight Python package)
2. `klight-catalog.yaml` in current working directory
3. `~/.klight/catalog.yaml` (personal overrides)

---

## Step 2 — Add Kustomize manifests

Under your infra repo `manifests/` tree:

```
manifests/
└── infrastructure/
    └── postgres-store/
        └── base/
            ├── kustomization.yaml
            ├── statefulset.yaml
            └── service.yaml
```

Copy from `kraken-light/manifests/infrastructure/postgres/` and rename resources (`postgres-store` instead of `postgres`).

Set `KLIGHT_MANIFESTS_DIR` when deploying:

```bash
export KLIGHT_MANIFESTS_DIR=/path/to/company-infra/manifests
klight from-repos ./services/* --env dev
```

---

## Step 3 — Reference in `klight.yaml`

```yaml
name: store-api
port: 8080
needs: [postgres-store, kafka]
env:
  DB_HOST: postgres-store
  DB_PORT: "5432"
  DB_NAME: store_db
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
```

klight starts **one** StatefulSet per unique `needs:` entry in the namespace.

---

## Setup Wizard detection

When scanning repos, the wizard compares each service's `needs:` list against built-in + local catalog entries. Missing entries appear as:

```
⚠ Custom infra detected
• store-api needs: postgres-store — not in built-in catalog

Options:
  a) Rename to postgres (single shared instance)
  b) Add postgres-store to klight-catalog.yaml
```

See [DevOps Team Setup](13-devops-team-setup.md) for the full wizard workflow.

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Unknown infra: postgres-store` | Add entry to `klight-catalog.yaml` or rename to built-in |
| Manifest not found | Check `KLIGHT_MANIFESTS_DIR` and `manifest:` path |
| Duplicate postgres pods | Two catalog entries with different names but same Service name — use unique resource names |

---

## Related docs

- [Service Profiles](09-service-profiles.md) — profiles declare which infra a stack needs
- [DevOps Team Setup](13-devops-team-setup.md) — company-infra pattern
- [Core Concepts](02-core-concepts.md) — how `needs:` resolves to StatefulSets
