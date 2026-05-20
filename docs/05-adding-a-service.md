# Adding a Service

## Option 1: klight.yaml (recommended — no K8s knowledge)

### Step 1: generate klight.yaml

```bash
klight init ./my-service
```

klight scans the repo and asks:
- Service name (detected from folder)
- Port (detected from EXPOSE in Dockerfile)
- What infra it needs (detected from dependencies)
- Depends on any other service?

### Step 2: review and customize

```yaml
# my-service/klight.yaml
name: my-service
port: 8080
health: /health
needs: [postgres, kafka]
env:
  # Write the EXACT env var names your code reads.
  # Auto-provided by needs: [postgres] → GLOBAL_POSTGRES_HOST=postgres
  # Add your service-specific ones:
  DB_NAME: my_service_db
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
  OTHER_SERVICE_URL: http://other-service:8081
```

**Important**: if your service calls another service, add it to `depends:`:
```yaml
depends:
  - other-service:8081/health
```
klight configures sentinel to wait for it.

### Step 3: deploy

```bash
klight local build-load my-service --path ./my-service
klight from-repos ./my-service ./other-service --env alice
```

---

## Option 2: Existing K8s manifests in deploy/ folder

If your service already has Kubernetes YAML:

```yaml
# my-service/klight.yaml
name: my-service
port: 8080
manifest: ./deploy/overlays/dev   # use these, don't generate new ones
needs: [postgres, kafka]          # klight still manages infra
```

klight applies your manifests with `kubectl apply -k deploy/overlays/dev` and injects sentinel as a transparent patch — your `deploy/` files stay clean.

---

## Option 3: Service in a separate DevOps infra repo

If manifests are in `company-infra/manifests/services/my-service/`:

```yaml
# my-service/klight.yaml
name: my-service
port: 8080
manifest: ../company-infra/manifests/services/my-service/overlays/dev
needs: [postgres]
```

Or set `KLIGHT_MANIFESTS_DIR=../company-infra/manifests` — klight finds the manifest automatically without the `manifest:` field.

---

## Option 4: Non-standard build (Gradle, SBT, Quarkus, monorepo)

```yaml
name: banking
port: 8080
health: /actuator/health
build:
  command: ./gradlew banking:jib --image=banking:local
  context: ../          # run from monorepo root
watch_paths:
  - banking/src/
  - banking-api-core/src/   # shared module
needs: [postgres, kafka]
env:
  SPRING_DATASOURCE_URL: jdbc:postgresql://postgres:5432/banking_db
```

---

## Adding custom infra (not in default catalog)

Add to `klight-catalog.yaml` at your project root:

```yaml
version: "1"
infra:
  my-vector-db:
    image: qdrant/qdrant:v1.8.4
    port: 6333
    provides:
      QDRANT_URL: http://my-vector-db:6333
```

Then use in klight.yaml: `needs: [postgres, my-vector-db]`

---

## Checklist

- [ ] `klight.yaml` in the service repo root
- [ ] `name` matches what other services use to call this service (DNS name)
- [ ] `port` and `health` are correct
- [ ] `needs:` lists all infra this service requires
- [ ] `depends:` lists all OTHER SERVICES this service needs healthy before starting
- [ ] `env:` has the env var names your code reads (not what klight provides)
- [ ] Migration configured if service has a DB schema
- [ ] `build:` added if no standard Dockerfile at root
