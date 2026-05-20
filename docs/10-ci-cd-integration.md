# CI/CD Integration

## PR environments

```yaml
# .github/workflows/pr.yml
on:
  pull_request:
    types: [opened, synchronize, closed]

jobs:
  create-or-update:
    if: github.event.action != 'closed'
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Setup klight
      run: |
        pip install klight
        # Import cluster kubeconfig
        klight connect --kubeconfig <(echo "${{ secrets.KUBE_CONFIG }}")
        klight use remote

    - name: Create/update PR environment
      run: |
        klight env create pr-${{ github.event.number }}
        # Option A: repos with klight.yaml
        klight from-repos ./service-a ./service-b \
          --env pr-${{ github.event.number }}
        # Option B: profiles in infra repo
        klight up vertical1 --env pr-${{ github.event.number }}

  destroy:
    if: github.event.action == 'closed'
    runs-on: ubuntu-latest
    steps:
    - run: klight env destroy pr-${{ github.event.number }} --yes
```

## Deploy to staging on merge

```yaml
# .github/workflows/staging.yml
on:
  push:
    branches: [main]

jobs:
  deploy:
    steps:
    - uses: actions/checkout@v4
    - run: pip install klight && klight use remote
    - run: |
        klight service deploy my-api \
          --env staging \
          --image ghcr.io/myorg/my-api:${{ github.sha }}
```

## Image update flow (cross-repo)

Service repo CI builds and notifies infra repo:

```yaml
# In service repo CI:
- name: Notify infra repo
  uses: peter-evans/repository-dispatch@v3
  with:
    token: ${{ secrets.INFRA_REPO_TOKEN }}
    repository: myorg/company-infra
    event-type: update-image
    client-payload: |
      {"service": "my-api", "image": "ghcr.io/myorg/my-api:${{ github.sha }}"}
```

## Required secrets

| Secret | Description |
|---|---|
| `KUBE_CONFIG` | Base64 kubeconfig for dev cluster |
| `DEV_POSTGRES_PASSWORD` | Dev DB password |
| `DEV_JWT_SECRET` | Dev JWT signing key |
| `INFRA_REPO_TOKEN` | PAT for cross-repo dispatch |
