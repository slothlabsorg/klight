# Getting Started

## Prerequisites

```bash
docker --version    # >= 24.0
python3 --version   # >= 3.11
kubectl version --client
minikube version    # >= 1.32
pip install klight
```

## Path A — You have service repos, no K8s YAML

### Step 1: generate klight.yaml for each service

```bash
klight init ./store-api        # detects port, dependencies, migration
klight init ./inventory-api
klight init ./store-web
```

klight scans Dockerfile, requirements.txt, package.json, build.gradle.kts and proposes a `klight.yaml`. Answer 3–4 questions, done.

Review and edit the generated file to confirm env var names match what your code reads.

### Step 2: build service images

```bash
klight local setup                                    # start minikube
klight local build-load store-api --path ./store-api
klight local build-load inventory-api --path ./inventory-api
klight local build-load store-web --path ./store-web
```

### Step 3: configure secrets

```bash
cp manifests/env/secrets/global.env.example manifests/env/secrets/global.env
# Edit: set POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET
```

### Step 4: create environment and deploy

```bash
klight env create alice --with-infra
klight from-repos ./store-api ./inventory-api ./store-web --env alice
```

### Step 5: open and verify

```bash
klight open store-web --env alice   # opens browser
klight ps --env alice               # all services green
klight unready --env alice          # should be empty
```

---

## Path B — Your infra repo has profiles (DevOps team setup)

```bash
git clone company-infra && cd company-infra
klight local setup
# Pre-load infra images (first time only)
klight preflight --fix
# Create environment and bring up a vertical
klight env create alice
klight up vertical1 --env alice
klight ui
```

---

## Path C — Use a remote cluster instead of minikube

```bash
# Get kubeconfig from your DevOps team
klight connect --kubeconfig ~/Downloads/company-dev.yaml
klight use remote
klight env create alice
klight up vertical1 --env alice    # runs on remote cluster
```

---

## Cleanup

```bash
klight env destroy alice --yes
```
