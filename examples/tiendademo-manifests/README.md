# TiendaDemo Kubernetes manifests

Kustomize manifests for profile-based deploy (`klight up store`).

## Layout

```
profiles/store.yaml       Profile definition
services/*/               Per-service Kustomize (base + overlays/dev)
jobs/*-dbmigrate/         Migration jobs
env -> ../../manifests/env                    (symlink)
infrastructure -> ../../manifests/infrastructure  (symlink)
```

Symlinks point at core `kraken-light/manifests/` so config and infra StatefulSets are shared.

## Usage

```bash
export KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml
export KLIGHT_MANIFESTS_DIR=/path/to/kraken-light/examples/tiendademo-manifests

klight env create store-test --with-infra
klight up store --env store-test
```

For local development with live code, prefer `klight from-repos` (see klight-suite-test SETUP.md).

## Migration v2

```bash
klight db migrate store-api-v2 --env store-test
```

Uses job at `jobs/store-api-v2-dbmigrate/`.
