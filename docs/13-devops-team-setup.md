# DevOps Team Setup

This guide covers how a small DevOps team sets up klight for multiple development verticals, so new developers get a full stack with one command.

## The model

```
company-infra/          ← DevOps team's repo (this guide)
├── klight.toml         ← local + remote cluster targets
├── klight-catalog.yaml ← custom infra beyond defaults
├── manifests/
│   ├── infrastructure/ ← postgres, kafka, redis StatefulSets
│   ├── services/       ← K8s manifests per service
│   ├── jobs/           ← DB migration jobs
│   └── profiles/       ← what services each vertical runs
└── README.md           ← developer onboarding (just follow this)
```

Service repos live separately (GitHub, GitLab). They may have their own `klight.yaml` or `deploy/` folders, or the DevOps team maintains all K8s YAML in `company-infra`.

## Composable profiles with includes:

```
core.yaml          postgres + kafka + redis + core-auth + core-api
vertical1.yaml     includes: [core] + vertical1-api
vertical2.yaml     includes: [core] + vertical2-api
```

`klight up vertical2 --env alice` automatically starts:
1. postgres, kafka, redis (from core)
2. core-auth, core-api (from core)
3. vertical2-api

No duplication. core services start once, shared by both verticals.

## Setting up local + remote targets

### klight.toml

```toml
[targets]
default = "local"
local   = "klight-demo"        # minikube
remote  = "company-dev"        # kubectl context for shared cluster

[remote]
api_url = "https://k8s.dev.mycompany.com"

[images]
registry = "ghcr.io/mycompany"
```

### Developer onboarding: local

```bash
# developer runs:
pip install klight
git clone company-infra && cd company-infra
klight local setup
klight preflight --fix      # downloads all needed images
klight env create alice
klight up vertical1 --env alice
```

### Developer onboarding: remote cluster

```bash
# DevOps team provides a kubeconfig or token
pip install klight
git clone company-infra && cd company-infra
klight connect --kubeconfig ~/company-dev.yaml
klight use remote
klight env create alice
klight up vertical1 --env alice    # runs on remote cluster
```

The developer switches between local and remote with one command:
```bash
klight use local
klight use remote
```

## Setting up the cluster (remote option)

### 1. Create namespace RBAC per developer

```yaml
# For each developer: create a ClusterRole that allows managing env-<name> namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: klight-developer
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["create", "delete", "get", "list"]
- apiGroups: ["", "apps", "batch"]
  resources: ["*"]
  verbs: ["*"]
```

### 2. Create a service account per developer (or use OIDC)

For now (no auth): one shared service account with kubeconfig distributed by DevOps team.

Future: OIDC integration so each developer authenticates with their company SSO.

### 3. Cluster-level infra (runs once, not per-namespace)

```bash
# Install once on the cluster (not managed by klight):
helm install datadog datadog/datadog -n datadog --create-namespace ...
helm install fluent-bit fluent/fluent-bit -n logging --create-namespace ...
helm install cert-manager jetstack/cert-manager -n cert-manager ...
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx ...
```

klight manages per-namespace resources. Datadog/logging run once per node.

## Managing service K8s manifests: two approaches

### Approach A: manifests in company-infra (DevOps controls)

DevOps team writes `manifests/services/my-service/base/` for every service.
Developers never touch K8s YAML.

This is what `klight up <profile>` uses.

### Approach B: manifests in each service repo (team controls)

Each team maintains `deploy/` in their service repo.
They add `klight.yaml` with `manifest: ./deploy/overlays/dev`.

DevOps team maintains `company-infra` only for:
- Infrastructure StatefulSets
- Profiles (which services belong to which vertical)
- Global config/secrets

### Hybrid (common): profiles + klight.yaml in service repos

```yaml
# manifests/profiles/vertical1.yaml
services:
  - name: vertical1-api
    # klight finds deploy/ from KLIGHT_MANIFESTS_DIR or klight.yaml manifest: field
```

## Adding a new service to a vertical

1. Service team creates `service-name/klight.yaml` in their repo
2. DevOps adds `manifests/services/service-name/` to company-infra (if no `manifest:` in klight.yaml)
3. DevOps adds service to the relevant `profiles/vertical1.yaml`
4. Commit and push to company-infra
5. All devs get it on next `git pull` + `klight up vertical1 --env alice`

## Profile for PR environments (CI)

```yaml
# .github/workflows/pr.yml
on:
  pull_request:
    types: [opened, synchronize, closed]
jobs:
  create:
    if: github.event.action != 'closed'
    steps:
    - uses: actions/checkout@v4
      with:
        repository: mycompany/company-infra
    - run: pip install klight
    - run: klight connect --kubeconfig ...
    - run: klight use remote
    - run: klight env create pr-${{ github.event.number }}
    - run: klight up vertical1 --env pr-${{ github.event.number }}

  destroy:
    if: github.event.action == 'closed'
    steps:
    - run: klight env destroy pr-${{ github.event.number }} --yes
```
