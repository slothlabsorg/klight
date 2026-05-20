# company-infra

> DevOps team's infrastructure repo. Developers clone this and get their full stack in one command.

## New developer setup (5 minutes total)

### Option A — Local (laptop, no cluster needed)

```bash
# 1. Install klight
pip install klight

# 2. Clone this repo
git clone https://github.com/mycompany/company-infra
cd company-infra

# 3. Start local cluster (first time ~3 min)
klight local setup

# 4. Pre-load infra images (first time ~5 min)
docker pull postgres:16-alpine redis:7-alpine apache/kafka:3.7.0
minikube image load postgres:16-alpine redis:7-alpine apache/kafka:3.7.0 --profile klight-demo

# 5. Build service images (or pull from registry)
klight local build-load core-auth   --path ../core-auth
klight local build-load core-api    --path ../core-api
klight local build-load vertical1-api --path ../vertical1-api
# OR use CI images: klight service deploy core-auth --image ghcr.io/mycompany/core-auth:main

# 6. Create environment and bring up your vertical
klight env create alice --with-infra
klight up vertical1 --env alice       # starts: postgres, redis, kafka, core-auth, core-api, vertical1-api

# 7. Open
klight open vertical1-api --env alice
klight ui
```

### Option B — Remote (shared dev cluster)

```bash
pip install klight
git clone https://github.com/mycompany/company-infra
cd company-infra

# Get cluster access (DevOps team gives you a kubeconfig or token)
klight connect --kubeconfig ~/Downloads/company-dev.yaml
# OR
klight connect --url https://k8s.dev.mycompany.com --token eyJhbGci...

# Switch to remote
klight use remote

# Create YOUR namespace and bring up your vertical
klight env create alice             # creates env-alice on the cluster
klight up vertical1 --env alice     # CI images pulled from registry automatically

# Flip back to local anytime
klight use local
```

## What runs in each profile

```
core    → postgres + redis + kafka + core-auth + core-api
vertical1 → core + vertical1-api
vertical2 → core + vertical2-api
```

Profiles compose via `includes:`. `vertical1` includes `core` automatically — you get all core services without listing them manually.

## Repo structure

```
company-infra/
├── klight.toml                      ← target config (local + remote)
├── klight-catalog.yaml              ← custom infra entries
├── manifests/
│   ├── env/
│   │   ├── config/global.env        ← shared config for all envs
│   │   └── secrets/global.env.example
│   ├── infrastructure/              ← StatefulSets (postgres, redis, kafka)
│   ├── services/
│   │   ├── core-auth/               ← K8s Deployment + Service + ConfigMap
│   │   ├── core-api/
│   │   ├── vertical1-api/
│   │   └── vertical2-api/
│   ├── jobs/                        ← DB migration Jobs
│   └── profiles/
│       ├── core.yaml                ← shared core services
│       ├── vertical1.yaml           ← includes: [core] + vertical1
│       └── vertical2.yaml           ← includes: [core] + vertical2
└── docs/
    └── adding-a-service.md
```

## Common commands

```bash
# Status
klight ps --env alice
klight unready --env alice

# Logs
klight logs core-api --env alice -f

# DB
klight db connect postgres --env alice
klight db query --env alice --db auth_db "SELECT count(*) FROM users"

# Hot reload while developing
klight watch vertical1-api --env alice --path ../vertical1-api

# Switch targets
klight use local
klight use remote
klight target                  # show current target

# Destroy when done
klight env destroy alice --yes
```

## Adding a new service to a vertical

1. Create `manifests/services/my-new-service/` (copy `_template/`)
2. Add the service to the vertical's profile YAML
3. If it needs a DB migration, add `manifests/jobs/my-new-service-migrate/`
4. Commit and push — all devs get it on next `git pull` + `klight up`

See `docs/adding-a-service.md` for details.
