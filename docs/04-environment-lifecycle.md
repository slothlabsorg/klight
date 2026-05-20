# Environment Lifecycle

## States

```
(none) → Creating → Active → [Paused] → Destroying → (none)
```

## Creating

```bash
klight env create alice                 # namespace + global config only
klight env create alice --with-infra    # + postgres + redis StatefulSets
```

What happens:
1. `kubectl create namespace env-alice`
2. Labels namespace `klight.env=alice`
3. Applies `manifests/env/config/` → `klight-global-config` ConfigMap
4. Applies `manifests/env/secrets/` → `klight-global-secrets` Secret
5. If `--with-infra`: deploys postgres + redis

## Listing

```bash
klight env list
```

## Destroying

```bash
klight env destroy alice --yes
```

Deletes namespace + everything in it (pods, PVCs, ConfigMaps). Irreversible. Add `--yes` to skip confirmation in CI.

## Pausing (save resources)

```bash
klight env pause alice    # scale all Deployments to 0 — databases keep their data
klight env resume alice   # scale back to 1
```

Use this when a long-running branch isn't actively being developed. Data is preserved.

## Environments with profiles

```bash
# DevOps-managed: profile handles infra + services + migrations
klight env create alice
klight up vertical1 --env alice
```

## Environments from repos

```bash
# Self-service: klight.yaml per repo, no profile needed
klight env create alice
klight from-repos ./svc-a ./svc-b --env alice
```

## TTL (auto-destroy)

Annotate the namespace:
```bash
kubectl annotate namespace env-alice klight.ttl-hours=24
```

The TTL operator (Roadmap v0.3) auto-destroys expired namespaces.

## RBAC

Recommended: developers can create/destroy their own `env-<name>` namespaces, not others'. CI service accounts manage `env-pr-*` namespaces. See `examples/company-infra/` for sample RBAC.
