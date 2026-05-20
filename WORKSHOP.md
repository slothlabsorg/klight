# klight — Video Workshop Script

Three worlds. Each one is a self-contained demo you can record independently.

**Before recording:** run through the pre-flight checklist in each world. Every command shown produces the exact output shown — if something differs, fix it first.

---

## World 1 — Solo Dev (Local Code, No CI)

> **Who this is for:** A developer who has the code locally and wants to run the full stack without Docker Compose, without setting up any CI pipeline, without touching Kubernetes directly.

### Pre-flight checklist

```bash
# These must pass before recording
docker info > /dev/null && echo "Docker OK"
minikube status -p klight-demo | grep -q "Running" && echo "Cluster OK"
ls ./klight-demo-store-api/klight.yaml 2>/dev/null && echo "Repo cloned OK"
```

If minikube is not running:
```bash
DOCKER_HOST=unix:///Users/dany/.docker/run/docker.sock \
  minikube start --profile klight-demo --driver=docker \
  --cpus=2 --memory=3072 --kubernetes-version=v1.30.0
```

### Setup for demo

```bash
# Clone the demo repos (simulating a local monorepo)
git clone https://github.com/slothlabsorg/klight-demo-inventory-api
git clone https://github.com/slothlabsorg/klight-demo-store-api
git clone https://github.com/slothlabsorg/klight-demo-store-web

# Verify klight.yaml is present in each
cat klight-demo-inventory-api/klight.yaml
```

---

### Script

---

**[INTRO — 30 seconds]**

> **[SAY]** "Today I'm going to show you how any developer — without knowing Kubernetes, without setting up CI — can run a full microservices stack on their laptop in under 5 minutes."
>
> **[SAY]** "I have three services here: a store API, an inventory API, and a web frontend. Each one has a `klight.yaml` — a small config file, about 10 lines. Let me show you what that looks like."
>
> **[DO]** `cat klight-demo-inventory-api/klight.yaml`

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

> **[SAY]** "That's all. This file tells klight what infrastructure to start, what order things should start in, and what environment variables to inject. Zero changes to the actual application code."

---

**[STEP 1 — Start the cluster — 45 seconds]**

> **[SAY]** "First time you use klight, you start a local Kubernetes cluster. This takes about 3 minutes the first time, then it's always running."
>
> **[DO]** `klight local setup`

```
Starting minikube profile: klight-demo
  CPUs: 2, Memory: 3072MB, Driver: docker
✓ minikube klight-demo is ready.
  kubectl context: klight-demo
```

> **[SAY]** "Done. Two CPUs, three gigabytes of RAM. klight uses minikube under the hood, but you never need to think about that."
>
> **[SAY]** "Before I deploy, I want to make sure my cluster has enough memory for what I'm about to run. Let me open the klight UI."
>
> **[DO]** `klight ui`
>
> **[SHOW]** Browser opens at `http://localhost:7700`. Point to the cluster status bar: `klight-demo  2 CPUs · 3.0GB  OK`
>
> **[SAY]** "The status bar up here always shows what cluster I'm targeting, how much RAM it has, and whether it's healthy."

---

**[STEP 2 — Build and load images — 60 seconds]**

> **[SAY]** "Now I build my service images and load them into the cluster. klight does the docker build and the minikube image load in one command."
>
> **[DO]** `klight local build-load inventory-api --path ./klight-demo-inventory-api`

```
Building inventory-api:local from klight-demo-inventory-api...
[docker build output...]
Loading inventory-api:local into minikube (klight-demo)...
✓ inventory-api:local is ready in minikube
```

> **[DO]** `klight local build-load store-api --path ./klight-demo-store-api`
> **[DO]** `klight local build-load store-web --path ./klight-demo-store-web`
>
> **[SAY]** "These images have the `:local` tag. klight automatically sets them to `imagePullPolicy: Never` — so the cluster never tries to pull them from a registry. Your code stays private, no CI needed."

---

**[STEP 3 — Bring up the stack — 60 seconds]**

> **[SAY]** "Now — one command to bring up the entire stack."
>
> **[DO]** Click `+ New environment` in the UI sidebar.
>
> **[SHOW]** The form appears. Type `dev` for env name, select `store` profile.
>
> **[SAY]** "The UI is showing me a sizing estimate right now. Profile 'store' needs about 2.8 GB. My cluster has 3 GB — it fits."
>
> **[SHOW]** Green banner: `Profile 'store': ~2.8 GB estimated  ✓ Fits`
>
> **[SAY]** "If it didn't fit, I'd get a warning with a one-click resize button. For now, let me run this in the terminal."
>
> **[DO]** `KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight up store --env dev`

```
Profile: store → dev

  Deploying infra/postgres...    ✓ infra/postgres
  Deploying infra/kafka...       ✓ infra/kafka
  Deploying inventory-api (inventory-api:local)...  ✓ inventory-api
  Deploying store-api (store-api:local)...          ✓ store-api
  Deploying store-web (store-web:local)...          ✓ store-web

Profile 'store' ready in 'dev'
```

> **[SAY]** "klight started postgres and kafka first, waited for them to be healthy, ran the database migrations, then started the services in the right order. You didn't write a single line of orchestration code."

---

**[STEP 4 — Check status — 30 seconds]**

> **[DO]** `KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight ps --env dev`

```
Environment: dev (namespace: env-dev)
┌────────────────┬───────┬─────────┬──────────┬──────┐
│ SERVICE        │ READY │ STATUS  │ RESTARTS │ AGE  │
├────────────────┼───────┼─────────┼──────────┼──────┤
│ inventory-api  │ 1/1   │ Running │        0 │ 2m   │
│ kafka          │ 1/1   │ Running │        0 │ 3m   │
│ postgres       │ 1/1   │ Running │        0 │ 3m   │
│ store-api      │ 1/1   │ Running │        0 │ 2m   │
│ store-web      │ 1/1   │ Running │        0 │ 2m   │
└────────────────┴───────┴─────────┴──────────┴──────┘
```

> **[SHOW]** Switch to the UI. Click on `dev` in the sidebar. The 5/5 grid appears.
>
> **[SAY]** "Five services, all green. Click any of them to see logs."
>
> **[DO]** Click `inventory-api` card.
>
> **[SHOW]** Logs panel slides up with live output.

---

**[STEP 5 — Edit code, hot-swap — 45 seconds]**

> **[SAY]** "Now the really useful part. I'm going to edit the inventory-api code and deploy it without restarting anything else."
>
> **[DO]** Open `klight-demo-inventory-api/app/main.py` in editor, make a small visible change.
>
> **[DO]** `klight replace inventory-api --with ./klight-demo-inventory-api --env dev`

```
Building inventory-api:local...
Loading into minikube...
Patching deployment inventory-api in env-dev...
✓ inventory-api replaced (rolling restart)
```

> **[SAY]** "klight rebuilt the image, loaded it, and did a rolling restart of only that one service. Everything else kept running. This is the inner dev loop."

---

**[OUTRO — 20 seconds]**

> **[SAY]** "To clean up:"
>
> **[DO]** `klight destroy dev`
>
> **[SAY]** "That deleted the entire namespace — postgres, kafka, all five services — in one command. No leftover containers, no volumes dangling around."
>
> **[SAY]** "The `klight.yaml` took 10 minutes to write. The rest is just: build, up, iterate."

---

## World 2 — Startup Team (Sync, No Local Clones)

> **Who this is for:** A developer who just joined a team. The DevOps person set everything up. This dev does NOT need to clone any service repo. The full stack runs on their laptop from CI images in under 3 minutes.

### Pre-flight checklist

```bash
# Cluster must be running
minikube status -p klight-demo | grep -q "Running" && echo "OK"

# Verify sync works
klight sync https://raw.githubusercontent.com/slothlabsorg/klight-demo-infra/main/klight-team.yaml 2>&1 | grep "Team"

# Verify env-tienda is up (for later steps)
KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight ps --env tienda 2>&1 | grep "Running" | wc -l
# Should show 5
```

If env-tienda is not running:
```bash
KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight up store --env tienda
```

Start the UI server for this session:
```bash
KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml \
  KLIGHT_MINIKUBE_PROFILE=klight-demo \
  uvicorn server:app --port 7700 --log-level error &
```

---

### Script

---

**[INTRO — 30 seconds]**

> **[SAY]** "It's your first week at a startup. They have five services, Kafka, Postgres — the whole stack. Normally you'd spend a day installing dependencies, fighting Docker Compose, asking a senior dev why it doesn't work on your machine."
>
> **[SAY]** "With klight, your onboarding is two commands."

---

**[STEP 1 — Sync team config — 45 seconds]**

> **[SAY]** "The DevOps person has already done all the work. They have a `klight-team.yaml` in their infrastructure repo. I just point klight at it."
>
> **[DO]** `klight sync https://raw.githubusercontent.com/slothlabsorg/klight-demo-infra/main/klight-team.yaml`

```
Syncing from:
  https://raw.githubusercontent.com/.../klight-demo-infra/main/klight-team.yaml

  Cached 4 service configs

Team 'slothlabsorg' configured
  Services:  4
  Profiles:  store, full
  Local target: klight-demo

  klight use local
  klight up store --env alice
```

> **[SAY]** "That's it. klight downloaded the team configuration — which services exist, where their Docker images are, how they're grouped into profiles. No git clones. No npm install. No reading 40 pages of README."

---

**[STEP 2 — Bring up the full stack — 60 seconds]**

> **[SAY]** "Now I bring up the store profile in my own isolated environment. I'm going to call it `tienda`."
>
> **[DO]** `KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight up store --env tienda`

```
Profile: store → tienda

  Deploying infra/kafka...       ✓ infra/kafka
  Deploying infra/postgres...    ✓ infra/postgres
  Deploying inventory-api (ghcr.io/slothlabsorg/klight-demo-inventory-api:main)
  ✓ inventory-api
  Deploying store-api (ghcr.io/slothlabsorg/klight-demo-store-api:main)
  ✓ store-api
  Deploying store-web (ghcr.io/slothlabsorg/klight-demo-store-web:main)
  ✓ store-web

Profile 'store' ready in 'tienda'
```

> **[SAY]** "Notice: the images are being pulled from `ghcr.io/slothlabsorg/...` — those are the CI images, built by GitHub Actions from the main branch. I never cloned any of those repos. Never ran a single `npm install` or `pip install`. The apps are running exactly as they'd run in staging."
>
> **[DO]** `KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight ps --env tienda`
>
> **[SHOW]** Table with 5/5 Running.

---

**[STEP 3 — The UI — 60 seconds]**

> **[DO]** `klight ui` → browser at `http://localhost:7700`
>
> **[SHOW]** Cluster status bar: `klight-demo  2 CPUs · 3.0GB  OK`
>
> **[SAY]** "The cluster status bar at the top tells me where I'm running — klight-demo, 2 CPUs, 3 gigabytes, healthy."
>
> **[DO]** Click `tienda` in the sidebar.
>
> **[SHOW]** 5 green cards: inventory-api, kafka, postgres, store-api, store-web — all showing `Running 1/1`.
>
> **[SAY]** "Five services, all green. This is my isolated namespace — `env-tienda`. My colleague can be running their own `env-alice` at the same time on the same laptop. They don't interfere."
>
> **[DO]** Click the `inventory-api` card.
>
> **[SHOW]** Logs panel slides up: health check pings rolling in green.
>
> **[SAY]** "Click any service to see its logs. This is a real Python FastAPI service receiving Kubernetes health check probes. It's real — not a mock, not a stub."

---

**[STEP 4 — Multiple environments — 30 seconds]**

> **[SAY]** "If I want to test a feature in parallel, I spin up another environment."
>
> **[DO]** Click `+ New environment` in sidebar. Type `alice`, select `store`.
>
> **[SHOW]** Green banner: `Profile 'store': ~2.8 GB estimated  ✓ Fits`
>
> **[SAY]** "klight tells me this profile needs 2.8 gigabytes and the cluster can handle it. The command to run:"
>
> **[SHOW]** `klight up store --env alice`
>
> **[SAY]** "Two minutes later, alice has her own postgres, her own kafka, her own store-api. Completely isolated. She can drop her database, she can break her kafka — it doesn't touch tienda."

---

**[STEP 5 — Setup Wizard (DevOps side) — 60 seconds]**

> **[SAY]** "I showed you the dev side. But how did the DevOps person set this up? Let me show you the Setup Wizard."
>
> **[DO]** Click `Setup Wizard` tab in the UI.
>
> **[SHOW]** The wizard with Step 1 form: Platform, Org, Token, Registry.
>
> **[SAY]** "Step 1: connect your Git platform. GitHub, GitLab, Bitbucket. Paste a token and your org name."
>
> **[SAY]** "Step 2: klight scans all your repos. It finds which ones have a `klight.yaml`, which have a `Dockerfile`, which have deploy manifests."
>
> **[SAY]** "Step 3: for repos that are missing a `klight.yaml`, klight generates one. It reads the Dockerfile to detect the port, figures out the health endpoint, writes the file."
>
> **[SAY]** "Step 4: generate `klight-team.yaml`, open PRs to each service repo to add the `klight.yaml`, and share the sync URL with the team."
>
> **[SAY]** "From that point on, any developer who joins: one command, two minutes, full stack."

---

**[OUTRO — 20 seconds]**

> **[SAY]** "klight sync. klight up. That's the entire workflow for a new team member. No reading docs about how to install the right version of Kafka. No fighting with docker-compose.override.yml. Just: sync, up, done."

---

## World 3 — Remote Cluster (Team on EKS/GKE)

> **Who this is for:** A growing team (10+ engineers) that has outgrown local minikube. A shared cloud cluster on EKS or GKE. DevOps sets it up once; each developer connects with one command.

> **Note:** For recording, you can simulate this with a second minikube profile (`k3d` also works well) or use a real EKS/GKE cluster. The commands are identical.

### Pre-flight checklist

```bash
# Remote cluster is reachable
kubectl --context my-remote-cluster get nodes 2>&1 | grep "Ready"

# klight is installed
klight --version

# You have DevOps-level access to the remote cluster
kubectl --context my-remote-cluster auth can-i create clusterroles
# → yes
```

### For simulating with a second minikube profile (no cloud account needed)

```bash
# Create a second minikube profile simulating the "remote" cluster
DOCKER_HOST=unix:///Users/dany/.docker/run/docker.sock \
  minikube start --profile klight-remote-sim --driver=docker \
  --cpus=2 --memory=3072 --kubernetes-version=v1.30.0

kubectl config use-context klight-remote-sim
```

---

### Script — Part A: DevOps configures the cluster (run once)

---

**[INTRO — 30 seconds]**

> **[SAY]** "Your team has 10 engineers. Local minikube is getting slow. You're on EKS. The platform team wants to give developers access to the cluster — but in a safe, isolated way. Nobody should be able to touch production, or another dev's environment."
>
> **[SAY]** "Here's how DevOps sets this up. One command."

---

**[STEP 1 — DevOps: setup-remote — 60 seconds]**

> **[SAY]** "The DevOps person runs this on the remote cluster — once, ever."
>
> **[DO]** `kubectl config use-context my-eks-cluster` (or the cluster name)
>
> **[DO]** `klight cluster setup-remote`

```
Setting up klight remote access on current cluster...

✓ Namespace klight-system
✓ ServiceAccount klight-dev
✓ ClusterRole klight-dev (namespace management + workloads)
✓ ClusterRoleBinding klight-dev

Remote access configured.

Token (valid 1 year): eyJhbGciOiJSUzI1NiIsImtpZCI6Ii...

Share with your devs:
  klight connect --url https://xxxxx.eks.amazonaws.com --token eyJhbGci...

After connecting:
  klight use klight-remote
  klight up store --env alice
```

> **[SAY]** "klight created a service account called `klight-dev` with minimal permissions: create and delete namespaces that match `env-*`, and full access inside those namespaces. Nothing else. A developer cannot touch `production`, `staging`, or any other developer's environment."
>
> **[SAY]** "klight generated a token valid for one year. The DevOps person sends that `klight connect` command to each developer over Slack or email. That's the entire onboarding."

---

### Script — Part B: Developer connects and deploys

---

**[STEP 2 — Dev: connect to remote cluster — 30 seconds]**

> **[SAY]** "Now switching to the developer's laptop. They received that one-liner from DevOps."
>
> **[DO]** `klight connect --url https://xxxxx.eks.amazonaws.com --token eyJhbGci...`

```
✓ Context 'klight-remote' configured → https://xxxxx.eks.amazonaws.com
  Switch to it: klight use klight-remote
```

> **[DO]** `klight use remote`

```
✓ Switched to ☁  remote: klight-remote
  klight up <profile> --env <name>
```

> **[DO]** `klight target`

```
Target: remote (klight-remote)
  Switch to local:  klight use local

  Configured targets:
    local    klight-demo
    remote   klight-remote  ←
```

> **[SAY]** "I'm now pointing at the remote cluster. Same CLI, same commands. klight uses whatever cluster is currently active."

---

**[STEP 3 — Dev: sync and up — 60 seconds]**

> **[DO]** `klight sync https://raw.githubusercontent.com/slothlabsorg/klight-demo-infra/main/klight-team.yaml`
>
> **[SAY]** "Sync is the same. Team config is the same. The only difference is where the environment runs."
>
> **[DO]** `klight up store --env alice`

```
Profile: store → alice

  Deploying infra/kafka...       ✓ infra/kafka
  Deploying infra/postgres...    ✓ infra/postgres
  Deploying inventory-api (ghcr.io/slothlabsorg/klight-demo-inventory-api:main)
  ✓ inventory-api
  Deploying store-api ...        ✓ store-api
  Deploying store-web ...        ✓ store-web

Profile 'store' ready in 'alice'
```

> **[DO]** `klight ps --env alice`
>
> **[SAY]** "Alice's environment is running on the cloud cluster. Her colleague Bob can do the same — `klight up store --env bob` — and get a completely isolated namespace."
>
> **[DO]** (on another terminal) `klight up store --env bob`
>
> **[SAY]** "Alice's postgres, Bob's postgres. Alice's kafka, Bob's kafka. They're in different namespaces. They don't share state. Bob can break his database — Alice doesn't notice."

---

**[STEP 4 — UI on remote — 30 seconds]**

> **[DO]** `klight ui`
>
> **[SHOW]** Cluster status bar shows the remote cluster name, not `klight-demo`.
>
> **[SAY]** "The UI always shows which cluster you're on. The status bar here says `klight-remote` — the cloud cluster. If I switch back to local:"
>
> **[DO]** `klight use local`
>
> **[SHOW]** Status bar updates to `klight-demo`.
>
> **[SAY]** "Same UI, same commands, different cluster. The UI just follows whatever `kubectl` context is active."

---

**[STEP 5 — Tear down — 20 seconds]**

> **[DO]** `klight use remote`
> **[DO]** `klight destroy alice`

```
Namespace env-alice deleted.
```

> **[SAY]** "Alice tears down her environment when she's done. The namespace is gone. Nothing left on the cluster. The next developer can reuse that name."

---

**[OUTRO — 30 seconds]**

> **[SAY]** "Let me recap what just happened. DevOps ran one command: `klight cluster setup-remote`. That created a service account with the minimum permissions needed — nothing more. Then each developer ran `klight connect` once. After that — `klight sync`, `klight up`, done."
>
> **[SAY]** "The same two commands that work on a laptop also work against EKS, GKE, AKS, or bare metal. No different YAML files. No different config. klight abstracts the cluster — you just tell it which one to use."

---

## After Recording — Regenerate Screenshots

After any UI change or before publishing, regenerate the World 2 screenshots:

```bash
cd klight-ui

# Make sure the server is running with the right cluster
KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml \
KLIGHT_MINIKUBE_PROFILE=klight-demo \
  uvicorn server:app --port 7700 --log-level error &

# Make sure env-tienda is up
KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml klight up store --env tienda

# Run screenshots
npm run screenshots:w2

# Review
open tests/screenshots/world2-sync/
```

World 1 screenshots (when World 1 is recorded):
```bash
npm run screenshots:w1   # runs after klight local build-load + klight up --env dev
```

World 3 screenshots (when remote cluster is configured):
```bash
KLIGHT_REMOTE_URL=https://... KLIGHT_REMOTE_TOKEN=eyJ... npm run screenshots:w3
```

---

## Quick Reference — Commands Used in All 3 Worlds

| Command | World | What it does |
|---------|-------|-------------|
| `klight local setup` | 1 | Start minikube cluster (2 CPUs, 3 GB) |
| `klight local build-load <svc> --path <dir>` | 1 | `docker build` + `minikube image load` |
| `klight local resize --memory 4096` | 1, 2 | Resize cluster (stops + restarts) |
| `klight replace <svc> --with <dir> --env <name>` | 1 | Hot-swap service with local build |
| `klight sync <url>` | 2, 3 | Download team config + cache service klight.yamls |
| `klight up <profile> --env <name>` | 1, 2, 3 | Deploy full stack to isolated namespace |
| `klight ps --env <name>` | 1, 2, 3 | Show pod status table |
| `klight logs <svc> --env <name>` | 1, 2, 3 | Tail logs |
| `klight ui` | 1, 2, 3 | Dashboard at http://localhost:7700 |
| `klight destroy <name>` | 1, 2, 3 | Delete namespace + everything in it |
| `klight cluster setup-remote` | 3 | DevOps: create SA + RBAC + token on cluster |
| `klight connect --url <u> --token <t>` | 3 | Dev: register remote cluster |
| `klight use remote` | 3 | Switch to remote cluster |
| `klight use local` | 3 | Switch back to minikube |
| `klight target` | 3 | Show current cluster target |
