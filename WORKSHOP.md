# klight Workshop — Video Script

Three worlds, one tool. Each world is a complete scenario you can demo independently.

---

## World 1 — Solo Dev (Local Monorepo)

**The story:** I'm a solo dev with a monorepo. I want to run my full stack locally without Docker Compose complexity.

### Prerequisites
- Docker Desktop running
- `klight` installed (`pip install klight`)

### Steps

```bash
# 1. Start a local cluster
klight local setup
# → minikube starts with 2 CPUs, 3 GB RAM

# 2. Build and load your service images
klight local build-load store-api --path ./store-api
klight local build-load inventory-api --path ./inventory-api
klight local build-load store-web --path ./store-web

# 3. Write klight.yaml for each service (or use the Setup Wizard)
# store-api/klight.yaml:
#   name: store-api
#   port: 8000
#   health: /health
#   needs: [postgres, kafka]

# 4. Bring up the stack
klight up store --env dev

# 5. Watch it come up
klight ps --env dev

# 6. Open the UI
klight ui   # → http://localhost:7700

# 7. View logs of any service
klight logs store-api --env dev

# 8. Edit code → rebuild → hot-swap (no cluster restart)
klight replace store-api --path ./store-api --env dev

# 9. Tear down
klight destroy dev
```

### Key points for video
- Show `klight local setup` output — fast, no config
- Show the cluster status bar in the UI: `klight-demo  2 CPUs · 3.0GB  Running`
- Show sizing banner: "Profile 'store': ~2.8 GB ✓ Fits"
- Show logs tab with live log output

---

## World 2 — Startup Team (Sync from Git)

**The story:** We're a 5-person startup. Our DevOps person set up the team config. Each dev can spin up the full stack without cloning any service repo.

### Prerequisites
- Docker Desktop running
- `klight` installed
- GitHub account with access to slothlabsorg (or your own org)

### Steps

```bash
# 1. DevOps creates klight-team.yaml and commits it to the infra repo
# (done once — shown in the Setup Wizard)

# 2. Any dev runs one command to sync the team config
klight sync https://raw.githubusercontent.com/slothlabsorg/klight-demo-infra/main/klight-team.yaml
# → Downloaded team config: slothlabsorg
# → Cached 4 service configs (store-api, inventory-api, store-web, sales-recorder)

# 3. Start a local cluster (if needed)
klight local setup

# 4. Bring up the store profile — uses ghcr.io images, no local clones
klight up store --env tienda
# → Deploying infra/postgres...   ✓
# → Deploying infra/kafka...      ✓
# → Deploying inventory-api (ghcr.io/slothlabsorg/klight-demo-inventory-api:main)
# → Deploying store-api           ✓
# → Deploying store-web           ✓

# 5. Check status
klight ps --env tienda

# 6. Open the UI to see the running environment
klight ui   # → http://localhost:7700

# 7. Each dev can have their own isolated environment
klight up store --env alice
klight up store --env bob
klight ps --env alice
klight ps --env bob

# 8. Tear down when done
klight destroy tienda
```

### Setup Wizard (shown in UI)
For teams starting from scratch, the Setup Wizard at http://localhost:7700 walks through:
1. Connect GitHub/GitLab → paste token + org name
2. Scan repos → shows which have `klight.yaml` + `Dockerfile`
3. Generate `klight.yaml` for repos that are missing it
4. Generate `klight-team.yaml` with all services + profiles
5. Open PRs to add `klight.yaml` to each repo
6. Distribute: `klight sync <url>`

### Key points for video
- `klight sync` is the only command a new dev needs before `klight up`
- No Docker Compose, no local clones required
- CI images pulled directly from ghcr.io into the cluster
- Multiple isolated environments running simultaneously

---

## World 3 — Remote Cluster (Team + EKS/GKE)

**The story:** We've grown to 10 engineers. Local minikube is too slow. We have a shared dev cluster on EKS. DevOps configures access; devs use one command.

### Prerequisites
- A running K8s cluster (EKS, GKE, AKS, k3d, or bare metal)
- DevOps has `kubectl` access to that cluster
- `klight` installed on both DevOps and dev laptops

### Steps

#### DevOps sets up the cluster (once)

```bash
# Switch to the remote cluster context
kubectl config use-context my-eks-cluster

# Configure klight remote access
klight cluster setup-remote
# → ✓ Namespace klight-system
# → ✓ ServiceAccount klight-dev
# → ✓ ClusterRole klight-dev (namespace management + workloads)
# → ✓ ClusterRoleBinding klight-dev
#
# Token generated (valid 1 year):
#   eyJhbGciOiJSUzI1NiIs...
#
# Share with your devs:
#   klight connect --url https://xxxxx.eks.amazonaws.com --token eyJhbGci...
```

#### Dev connects (once per laptop)

```bash
# Paste the command DevOps shared
klight connect --url https://xxxxx.eks.amazonaws.com --token eyJhbGci...
# → ✓ Context 'klight-remote' configured

# Switch to remote cluster
klight use remote

# Verify you're on the right cluster
klight target
# → Target: remote (klight-remote)
```

#### Dev workflow (same commands as local)

```bash
# Sync team config (same as World 2)
klight sync https://raw.githubusercontent.com/slothlabsorg/klight-demo-infra/main/klight-team.yaml

# Bring up your own environment on the remote cluster
klight up store --env alice
klight ps --env alice

# Open the UI connected to remote
klight ui

# Colleagues work in parallel, fully isolated
# alice → namespace env-alice
# bob   → namespace env-bob
# carol → namespace env-carol

# Tear down your environment when done
klight destroy alice
```

### RBAC: what each dev can do

The `klight-dev` service account grants:
- Create/delete namespaces matching `env-*`
- Full access to pods, deployments, services, configmaps, secrets within those namespaces
- Cannot touch other namespaces (e.g. `production`, `staging`, other devs' `env-*`)

### Key points for video
- `klight cluster setup-remote` is the only infra change needed
- Devs get a token — no kubeconfig files to share, no VPN required
- Same `klight up` / `klight ps` commands work against local or remote
- Perfect for teams that outgrow minikube or need shared GPU/large-memory nodes

---

## Cluster Sizing — Smart Warnings

klight estimates memory before you deploy so you don't hit OOMKilled surprises.

```bash
# Check sizing for a profile before bringing it up
curl http://localhost:7700/api/local/sizing/store
# {
#   "profile": "store",
#   "service_count": 3,
#   "infra": ["kafka", "postgres"],
#   "estimated_mb": 2816,
#   "recommended_mb": 3072
# }

# Resize the cluster if needed
klight local resize --memory 4096
# → Stopping cluster...
# → Starting with new resources...
# → klight-demo resized: 2 CPUs, 4096 MB
```

In the UI:
- Cluster bar always shows: `klight-demo  2 CPUs · 3.0GB  OK`
- "+ New environment" shows sizing estimate for each profile
- If it doesn't fit: "⚠ ~4.5 GB — cluster may be unstable  [Resize to 5 GB →]"

---

## Screenshots

All UI screenshots are in `klight-ui/tests/screenshots/`:

| World | Screenshot | Description |
|-------|-----------|-------------|
| W2 | `world2-sync/02-cluster-status-bar.png` | Cluster bar: klight-demo 2 CPUs · 3.0GB |
| W2 | `world2-sync/03-tienda-running.png` | 5/5 services running |
| W2 | `world2-sync/04-service-detail-inventory-api.png` | Service card grid |
| W2 | `world2-sync/05-logs-inventory-api.png` | Live logs panel |
| W2 | `world2-sync/06b-new-env-sizing-banner.png` | Sizing: ~2.8 GB ✓ Fits |
| W2 | `world2-sync/07-resize-cluster-dialog.png` | Resize dialog |
| W2 | `world2-sync/08-setup-wizard-tab.png` | Setup Wizard |

To regenerate screenshots:
```bash
cd klight-ui
KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml uvicorn server:app --port 7700 &
npm run screenshots:w2
open tests/screenshots/world2-sync/
```

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `klight local setup` | Start minikube cluster (2 CPUs, 3 GB) |
| `klight local resize --memory 4096` | Resize cluster |
| `klight local status` | Show cluster status + loaded images |
| `klight sync <url>` | Download team config + cache service configs |
| `klight up <profile> --env <name>` | Deploy full stack to a new environment |
| `klight ps --env <name>` | Show pod status for an environment |
| `klight logs <svc> --env <name>` | Tail logs |
| `klight destroy <name>` | Delete the namespace and everything in it |
| `klight replace <svc> --path . --env <name>` | Hot-swap service with local build |
| `klight cluster setup-remote` | Configure remote cluster access (DevOps) |
| `klight connect --url <url> --token <token>` | Register remote cluster (dev) |
| `klight use remote` | Switch to remote cluster |
| `klight use local` | Switch back to local minikube |
| `klight target` | Show current cluster target |
| `klight ui` | Open dashboard at http://localhost:7700 |
