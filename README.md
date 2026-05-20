# klight

> Run your app locally exactly like in production — without knowing Kubernetes exists.

klight gives every developer an isolated, full-stack environment on their laptop or on a shared cluster. One command brings up databases, message brokers, and all your services in the right order. Another command tears it all down.

Inspired by how SoFi's internal Kraken platform works for 500+ engineers across 840+ microservices. klight brings those patterns to teams of 3–50.

---

## Quick start (5 minutes)

```bash
pip install klight
klight local setup                          # starts minikube (first time: ~3 min)
klight from-repos ./my-api ./my-worker --env alice
klight open my-api --env alice              # opens browser
```

That's it. No Kubernetes YAML. No Docker Compose. No "works on my machine."

---

## How it works

Each service adds a `klight.yaml` (10–20 lines). klight reads it and knows:
- What infrastructure to start (postgres, kafka, redis, S3...)
- What order to start services (dependency graph)
- What environment variables to inject (the names your code already reads)
- How to build the Docker image (standard Dockerfile or custom command)

```
your-cluster/
├── namespace: env-alice     ← your full stack, isolated
│   ├── postgres StatefulSet
│   ├── kafka StatefulSet
│   ├── my-api Deployment    → reads DB_HOST=postgres (injected by klight)
│   └── my-worker Deployment → reads KAFKA_BOOTSTRAP_SERVERS=kafka:9092
│
└── namespace: env-pr-123    ← PR environment, auto-created on PR open
```

---

## The klight.yaml

Add one to your service repo. The VS Code extension gives you autocomplete.

```yaml
# yaml-language-server: $schema=https://klight.dev/schema/klight.yaml.json
name: my-api
port: 8080
health: /health

needs: [postgres, kafka]   # klight starts these in the namespace

env:
  # Write the EXACT env var names your code already reads.
  # klight injects these — zero code changes needed.
  DB_HOST: postgres
  DB_NAME: my_api_db
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
  OTHER_SERVICE_URL: http://other-service:8081
```

---

## Examples by language and scenario

### Simple Python service

```yaml
name: inventory-api
port: 8081
health: /health
needs: [postgres, kafka]
migration:
  command: ["python", "-m", "app.migrate"]
env:
  DB_HOST: postgres
  DB_NAME: inventory_db
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
```

### Node.js service

```yaml
name: sales-recorder
port: 3002
health: /health
needs: [postgres, kafka]
env:
  DB_HOST: postgres
  DB_NAME: sales_db
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
```

### Kotlin / Spring Boot (standard Dockerfile)

```yaml
name: billing-service
port: 8082
health: /actuator/health
needs: [kafka, localstack]
env:
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
  AWS_ENDPOINT_URL: http://localstack:4566   # LocalStack in dev, empty = real AWS
  S3_BUCKET_NAME: invoices
  TWILIO_ACCOUNT_SID: ""   # optional — leave empty to log SMS instead of sending
```

### Spring Boot with Gradle Jib (no Dockerfile)

```yaml
name: banking
port: 8080
health: /actuator/health
build:
  command: ./gradlew banking:jib --image=banking:local
  context: ../                 # monorepo root
watch_paths:
  - banking/src/
  - banking-api-core/src/      # shared library this service uses
needs: [postgres, kafka, redis]
env:
  SPRING_DATASOURCE_URL: jdbc:postgresql://postgres:5432/banking_db
  SPRING_KAFKA_BOOTSTRAP_SERVERS: kafka:9092
  SPRING_DATA_REDIS_HOST: redis
```

### Quarkus (Maven)

```yaml
name: quarkus-api
port: 8080
health: /q/health
build:
  command: ./mvnw package -Dquarkus.container-image.build=true -Dquarkus.container-image.name=quarkus-api -Dquarkus.container-image.tag=local
needs: [postgres]
env:
  QUARKUS_DATASOURCE_JDBC_URL: jdbc:postgresql://postgres:5432/quarkus_db
```

### Rust (with Dockerfile)

```yaml
name: data-processor
port: 9000
health: /health
# Has a Dockerfile — klight uses it automatically, no build: needed
needs: [kafka, redis]
env:
  KAFKA_BROKERS: kafka:9092
  REDIS_URL: redis://redis:6379
```

### Service with existing K8s manifests in deploy/ folder

The service team already wrote their K8s YAML. klight uses it as-is:

```yaml
name: sales-recorder
port: 3002
manifest: ./deploy/overlays/dev   # use existing manifests, don't generate new ones
needs: [postgres, kafka]           # klight still manages infra startup
```

klight injects `sentinel` (startup ordering) as a transparent patch — the `deploy/` files stay clean.

### Service pointing to a separate DevOps/infra repo

```yaml
name: payments-api
port: 8080
manifest: ../mycompany-infra/manifests/services/payments-api/overlays/dev
needs: [postgres, kafka]
```

Or set `KLIGHT_MANIFESTS_DIR=../mycompany-infra/manifests` — klight auto-finds the service manifest.

### Using real external infra (instead of local StatefulSet)

Connect to a real Redis, real Kafka, etc. for debugging against staging data:

```yaml
name: my-api
port: 8080
needs:
  postgres:
    mode: local                         # start local postgres StatefulSet
  kafka:
    mode: external                      # don't start kafka, point to real one
    KAFKA_BOOTSTRAP_SERVERS: kafka.staging.mycompany.com:9092
```

### Adding AI / ML infrastructure

```yaml
name: recommendation-engine
port: 8080
needs: [postgres, ollama, chromadb]   # runs Ollama (LLMs) + ChromaDB locally
env:
  OLLAMA_BASE_URL: http://ollama:11434
  CHROMA_URL: http://chromadb:8000
```

After deploy, pull a model:
```bash
klight exec ollama --env alice -- ollama pull llama3
```

---

## Three team scenarios

### Scenario A — Dev with no K8s knowledge (zero config)

```bash
git clone my-service-repo
pip install klight
klight local setup
klight init ./my-service-repo     # scan repo, ask 3 questions, generate klight.yaml
klight from-repos ./my-service-repo --env alice
klight ui                         # open dashboard
```

### Scenario B — Self-service team (klight.yaml as part of delivery)

```bash
# Each service repo has klight.yaml already committed by the team
git clone store-api inventory-api store-web
klight local setup
klight from-repos ./store-api ./inventory-api ./store-web --env alice
```

### Scenario C — DevOps team manages central infra repo

```bash
git clone mycompany-infra
# Profiles in mycompany-infra/manifests/profiles/payments.yaml
klight up payments --env alice
```

---

## CLI reference

### Environment management
```bash
klight env create alice [--with-infra]     # create isolated environment
klight env list                            # list all environments
klight env destroy alice --yes             # destroy environment
klight env pause alice                     # scale to 0 (save resources)
klight env resume alice
```

### Deploying from repos
```bash
klight from-repos ./svc-a ./svc-b --env alice          # klight.yaml → deploy
klight from-repos ./svc-a --env alice --timeout 300
```

### Profiles (grouped services)
```bash
klight up payments --env alice             # profile defined in manifests/profiles/
klight down payments --env alice
```

### Service operations
```bash
klight ps --env alice                      # pretty status table
klight unready --env alice                 # show broken services + fix hints
klight logs my-api --env alice -f          # stream logs
klight open my-api --env alice             # port-forward + open browser
klight exec my-api --env alice -- sh       # exec into pod by service name
klight service restart my-api --env alice  # rolling restart
```

### Database operations
```bash
klight db connect postgres --env alice           # open psql
klight db query --env alice --db my_db "SELECT count(*) FROM users"
klight db migrate my-api --env alice             # run migration job
```

### Local development
```bash
klight local setup                               # start minikube klight-demo
klight local build-load my-api --path ./my-api   # docker build + minikube image load
klight local status                              # show minikube status + loaded images
klight preflight ./my-api ./my-worker            # check what images are missing
klight preflight ./my-api --fix                  # auto-build/pull missing images
klight watch my-api --env alice --path ./my-api  # hot reload on file change
```

### UI and init
```bash
klight ui                                        # open web dashboard (localhost:7700)
klight init ./my-service                         # generate klight.yaml from Dockerfile scan
klight init ./my-service --yes                   # non-interactive (use detected defaults)
```

---

## The infra catalog

klight ships with built-in infrastructure. Add custom entries without modifying klight.

**Built-in:** `postgres`, `mysql`, `mongodb`, `redis`, `kafka`, `rabbitmq`, `localstack`, `elasticsearch`, `ollama`, `chromadb`, `vault`

**Add your own** in `klight-catalog.yaml` at your project root:

```yaml
version: "1"
infra:
  my-vector-db:
    description: Custom vector database
    image: qdrant/qdrant:v1.8.4
    port: 6333
    manifest: infrastructure/qdrant/base   # optional K8s manifest
    provides:
      MY_VECTOR_DB_URL: http://my-vector-db:6333

  company-redis-cluster:
    description: Company Redis Cluster
    image: redis:7-alpine
    port: 6379
    provides:
      REDIS_URL: redis://company-redis-cluster:6379
```

---

## klight.yaml autocomplete in VS Code

Add to `.vscode/settings.json`:
```json
{
  "yaml.schemas": {
    "https://klight.dev/schema/klight.yaml.json": "klight.yaml"
  }
}
```

Or add to the top of your `klight.yaml`:
```yaml
# yaml-language-server: $schema=https://klight.dev/schema/klight.yaml.json
```

---

## How is this different from Docker Compose?

| | Docker Compose | klight |
|---|---|---|
| Isolation | Shared network | Each dev gets their own namespace |
| Scale | One instance per machine | 10 devs = 10 isolated stacks |
| CI/CD | Manual or custom scripts | Built-in PR environments |
| K8s parity | Only Docker containers | Real Kubernetes — staging/prod match |
| Multi-service | Yes | Yes + dependency ordering |
| Existing K8s manifests | No | Yes — use deploy/ as-is |
| Service mesh | No | Yes (if enabled) |

---

## Troubleshooting

**Pod stuck in `Init:0/1`**
```bash
klight logs my-api --env alice -c sentinel   # see what sentinel is waiting for
kubectl -n env-alice describe pod <pod>      # see events
```

**`klight from-repos` says image missing**
```bash
klight preflight ./my-api ./my-worker        # shows exactly what's missing
klight preflight --fix                       # auto-fix
```

**Wrong kubectl context (deployed to wrong cluster)**
```bash
kubectl config current-context              # check where you are
kubectl config use-context klight-demo      # switch to minikube
# Or use: export KUBECONFIG=/tmp/klight-demo.yaml
```

**Service crashes immediately**
```bash
klight logs my-api --env alice              # check app logs
klight unready --env alice                  # quick health summary
```

**Kafka consumer not receiving messages**
```bash
klight exec kafka --env alice -- /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --list
```

---

## Product roadmap

- [x] Core: env create/destroy, from-repos, profiles
- [x] Dev UX: ps, unready, open, exec, watch, preflight
- [x] Existing manifests: manifest: field in klight.yaml
- [x] External infra: mode: external in needs
- [x] Extendable catalog: klight-catalog.yaml
- [x] Web UI: klight ui (localhost:7700)
- [ ] Helm chart for cluster installation (klight-operator)
- [ ] Web UI: enrollment wizard, live log streaming
- [ ] `klight ai diagnose` — Claude explains pod failures
- [ ] TTL operator: auto-destroy PR environments
- [ ] Cost reporting: `klight cost --env alice`
- [ ] GitHub App: auto PR environments + comments
