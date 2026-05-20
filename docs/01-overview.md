# Overview

## What is klight?

klight gives every developer an isolated, full-stack Kubernetes environment on their laptop or on a shared cluster. One command brings up databases, message brokers, and all services in dependency order.

Inspired by SoFi's internal Kraken platform (840+ microservices, isolated environments per developer). klight brings those patterns to teams of 3–50.

## Three ways to use it

**1. Zero config** — developer with just a Dockerfile:
```bash
klight init ./my-service           # scan repo, generate klight.yaml (3 questions)
klight from-repos ./my-service ./other-service --env alice
```

**2. Self-service** — each service repo has klight.yaml:
```bash
klight from-repos ./service-a ./service-b ./frontend --env alice
```

**3. DevOps-managed** — company infra repo with profiles:
```bash
git clone company-infra && cd company-infra
klight up vertical1 --env alice    # one command, everything up
```

## Local vs remote

Same commands, two targets:
```bash
klight use local    # minikube on your laptop (default)
klight use remote   # shared dev cluster (company's)
klight target       # show where you are
```

## How isolation works

```
cluster/
├── namespace: env-alice     ← your full stack, isolated
├── namespace: env-pr-123    ← colleague's PR (isolated)
└── namespace: env-staging   ← persistent staging
```

## The klight.yaml (10–20 lines per service)

```yaml
# yaml-language-server: $schema=https://klight.dev/schema/klight.yaml.json
name: inventory-api
port: 8081
needs: [postgres, kafka]   # klight starts these in the namespace
env:
  DB_HOST: postgres         # exact names your code already reads
  KAFKA_BOOTSTRAP_SERVERS: kafka:9092
```

Services with existing K8s manifests reference them via `manifest:` — klight uses those instead of generating new ones.
