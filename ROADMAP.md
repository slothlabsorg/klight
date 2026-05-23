# klight — Roadmap

Last updated: 2026-05-21

---

## ✅ Done — Phase 1 (Foundation)

- Architecture, sentinel init container, Kustomize base/overlay templates
- CLI scaffold: `env`, `service`, `db`, `profile`, `ps`, `unready`, `open`, `exec`, `logs`
- `klight local setup/resize/build-load/status` — minikube klight-demo profile
- `klight from-repos` — World 1: deploy from local klight.yaml files
- `klight up/destroy` — World 2/3: deploy from team-synced profiles
- `klight sync` — download + cache klight-team.yaml from URL
- `klight replace` — hot-swap a running service with local build
- `klight cluster setup-remote` — create SA + RBAC + 1-year token for DevOps
- `klight connect --url --token` / `--kubeconfig` — register remote cluster
- `klight use local/remote` + `klight target` — switch cluster targets
- `klight watch`, `klight preflight`, `klight init` (scaffold)
- `klight ui` — FastAPI dashboard at localhost:7700
  - Cluster status bar (CPUs, RAM, context)
  - Environment list with service cards
  - Live log streaming per service
  - New environment form with sizing banner + OOM warning
  - Cluster resize dialog
  - Setup Wizard tab (GitHub scan + klight-team.yaml generator)
- Infrastructure catalog: postgres, kafka, redis, mongodb, rabbitmq, localstack, elasticsearch
- Custom catalog via `klight-catalog.yaml`
- klight.yaml JSON schema (`$schema=https://slothlabsorg.github.io/klight/schema/klight.yaml.json`)
- `manifest:` field — use existing K8s manifests instead of generating
- Sentinel: `busybox:stable-uclibc`, TCP + HTTP health polling
- Playwright test suite: world1-local, world2-sync, world3-remote (all passing)
- WORKSHOP.md — video scripts for all 3 worlds with speech + screen actions
- slothlabs.org/klight — landing page with real screenshots
- slothlabs.org/klight/docs — full docs with sidebar navigation
- Demo repos on slothlabsorg GitHub: inventory-api, store-api, store-web, infra

---

## 🔥 Next sprint — v0.2 (High priority, immediate value)

### `klight watch` — Tilt-style live reload
Auto-detect file changes → rebuild → replace. The killer DX feature Tilt has that klight needs.
```bash
klight watch store-api --env dev   # watches ./store-api, rebuilds+replaces on change
klight watch --all --env dev       # watch all locally-built services
```
Files: `klight/klight/commands/watch.py` (scaffold exists, needs implementation)

### PyPI publish — `pip install klight` from the public registry
Currently only installable from source. Real adoption requires a published package.
- Set up `pyproject.toml` properly, GitHub Action to publish on tag
- Test install from PyPI in a clean venv

### `klight preload-infra` — pull + load all infra images into minikube
Eliminates the ImagePullBackOff issue on fresh clusters.
```bash
klight local preload-infra         # pulls postgres, kafka, redis, etc. into minikube
```
Files: `klight/klight/commands/local.py`

### Context validation guard
Warn (or refuse) if current kubectl context matches a production pattern.
Currently: multiple SoFi contexts in ~/.kube/config co-exist with klight-demo.
Files: `klight/klight/commands/_context.py` (new) — called from `up`, `from-repos`, `destroy`

### klight.yaml JSON schema published to GitHub Pages
`$schema=https://slothlabsorg.github.io/klight/schema/klight.yaml.json` — published via GitHub Pages.
Schema lives in `schema/klight.yaml.json`; the `pages.yml` workflow deploys it on every push to main.

---

## 🎯 Q3 2026 — v0.3 (Team & adoption features)

### GitHub Action — PR environments
```yaml
# .github/workflows/preview.yml
on: [pull_request]
jobs:
  preview:
    steps:
      - run: klight up store --env pr-${{ github.event.number }}
      - run: echo "URL=http://store-web.env-pr-${{ github.event.number }}.svc:3000" >> $GITHUB_ENV
  cleanup:
    on: [pull_request closed]
    steps:
      - run: klight destroy pr-${{ github.event.number }}
```
Differentiates klight vs Tilt (local only) and closes the gap with Signadot.

### Namespace TTL operator
Auto-destroy environments after N hours. Critical for shared clusters to prevent resource leak.
```yaml
# in klight-team.yaml
ttl:
  pr_environments: 24h
  dev_environments: 72h
```
Implementation: K8s controller or CronJob that checks namespace annotations.

### `klight diagnose` — AI-powered broken pod analysis
```bash
klight diagnose --env alice
# > inventory-api CrashLoopBackOff
# > Logs: "Connection refused to postgres:5432"
# > Likely cause: postgres not yet ready or wrong DB_HOST
# > Suggested fix: check `klight ps --env alice` for postgres status
```
Calls Claude API with pod events + last 50 log lines. Huge differentiator vs all competitors.
Files: `klight/klight/commands/diagnose.py` (new)

### `klight init` — AI-scan a repo and generate klight.yaml
Currently a basic scaffold. Enhance with:
- Detect framework (FastAPI, Django, Spring Boot, Express, Rails)
- Detect DB from ORM imports / requirements.txt / build.gradle
- Detect Kafka from import patterns
- Propose complete klight.yaml with correct env var names

### klight.dev domain + docs site
Currently only slothlabs.org/klight. A dedicated domain adds credibility for DevOps teams.
Point klight.dev → slothlabs.org/klight initially, then a standalone site later.

---

## 🚀 Q4 2026 / Enterprise — v1.0

### Helm chart — `helm install klight klight/klight-operator`
- Installs RBAC for klight-dev service account
- Optional: klight dashboard as a K8s Deployment
- Makes setup 1 command for DevOps instead of running `klight cluster setup-remote`

### klight Cloud — hosted SaaS
- No local cluster needed
- Tenant gets a shared EKS cluster partition
- Environments provisioned on demand, billed by CPU-hour
- GitHub App integration: PR → env in 90 seconds

### Cost reporting
```bash
klight cost --env alice            # show CPU + RAM request costs
klight cost --all                  # all active environments
```
Reads K8s resource requests, multiplies by cloud pricing. 
Useful for shared clusters where DevOps needs to justify cost.

### Network policies + RBAC hardening
- Deny-all NetworkPolicy per namespace, explicit allowlist per `needs:`
- Read-only developer role (can't delete namespaces or scale to 0)
- Audit log for all `klight destroy` calls

### Observability auto-provisioning
- Prometheus + Grafana deployed via `klight local setup --with-observability`
- Per-environment Grafana dashboard provisioned on `klight up`
- OpenTelemetry collector StatefulSet in klight-system namespace

---

## Competitive moat — what makes klight unmatchable

| Differentiator | Tilt | Signadot | Skaffold | **klight** |
|---|---|---|---|---|
| Zero K8s YAML | ❌ | ❌ | ❌ | **✅** |
| Built-in infra catalog | ❌ | ❌ | ❌ | **✅** |
| Team sync from 1 URL | ❌ | ⚠️ Admin UI | ❌ | **✅** |
| Local + remote, same CLI | ⚠️ | ✅ | ⚠️ | **✅** |
| New dev in < 5 min | ⚠️ | ⚠️ | ⚠️ | **✅** |
| AI diagnose | ❌ | ❌ | ❌ | **🔜 v0.3** |
| Free / OSS | ⚠️ | ❌ $$ | ✅ | **✅** |

## Out of scope (intentionally)
- VM-based environment pools
- Consul / Istio service mesh
- Multi-cloud federation
- On-premise bare metal
