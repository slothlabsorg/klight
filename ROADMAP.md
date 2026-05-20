# klight — Roadmap

## Phase 1 — Foundation (current)

Goal: core platform patterns documented and working templates in place.

- [x] Architecture design and documentation
- [x] Kustomize base/overlay structure for services
- [x] Infrastructure StatefulSets (Postgres, Redis, Vault)
- [x] `sentinel` init container image
- [x] DB migration Job template
- [x] `klight` CLI scaffold (env, service, db, profile commands)
- [x] GitHub Actions PR environment workflow
- [ ] End-to-end example: 3-service todo app deployed with klight
- [ ] Publish `klight-sentinel` image to a public registry
- [ ] Publish `klight` to PyPI

## Phase 2 — Developer Experience

Goal: smooth day-to-day workflow for a 3–10 person engineering team.

- [ ] `klight env clone <from> <to>` — clone environment with data
- [ ] `klight env pause / resume` — scale all deployments to 0/1 to save cost
- [ ] `klight logs <service> --env <name>` — stream logs from any env
- [ ] `klight db connect <service> --env <name>` — open psql/redis-cli session
- [ ] `klight status --env <name>` — show pod health for all services in environment
- [ ] Web UI (FastAPI + React) for non-CLI users — similar to kraken2/web
- [ ] Slack notifications on environment create/destroy and deploy

## Phase 3 — Platform Hardening

Goal: production-grade reliability and security.

- [ ] External Secrets Operator integration guide + manifests
- [ ] RBAC templates (namespace-scoped roles for dev/CI/read-only)
- [ ] NetworkPolicy templates (deny-all + explicit service allowlists)
- [ ] Resource quotas per namespace (prevent runaway environments)
- [ ] Cost reporting: `klight cost --env <name>` (reads K8s resource requests)
- [ ] Namespace TTL operator: auto-destroy PR environments after N days
- [ ] Horizontal Pod Autoscaler templates for staging/prod

## Phase 4 — Observability

Goal: same visibility as a full platform team — without the overhead.

- [ ] Prometheus + Grafana manifests (or integration with existing stack)
- [ ] Per-environment dashboards auto-provisioned on `klight env create`
- [ ] Distributed tracing (OpenTelemetry collector StatefulSet)
- [ ] Alerting templates for common failure modes (pod CrashLoop, OOM, DB connection exhaustion)
- [ ] `klight diagnose --env <name>` — automated health check and remediation hints

## Out of scope (intentionally)

- VM-based environment pools (use namespaces instead)
- Consul service mesh (use CoreDNS + K8s Services)
- Multi-cloud federation
- On-premise bare metal support
