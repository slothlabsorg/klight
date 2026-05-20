# CLI Reference

## Install

```bash
pip install klight
klight --help
```

## Target management

```bash
klight use local          # switch to minikube klight-demo
klight use remote         # switch to configured remote cluster
klight use <ctx-name>     # switch to any kubectl context by name
klight target             # show current target (local/remote/custom)
klight connect --kubeconfig ~/path/to/kube.yaml   # import remote kubeconfig
klight connect --url https://k8s.company.com --token eyJ...
```

## Environment lifecycle

```bash
klight env create <name> [--with-infra]   # create namespace + global config
klight env destroy <name> [--yes]         # destroy everything (irreversible)
klight env list                           # list all klight environments
klight env describe <name>                # show pods + jobs
klight env pause <name>                   # scale to 0 (save resources, keep data)
klight env resume <name>                  # scale back to 1
```

## Deploy from repos (klight.yaml)

```bash
klight from-repos ./svc-a ./svc-b ./frontend --env alice
klight from-repos ./svc-a --env alice --timeout 300
```

Reads `klight.yaml` from each repo. Spins up infra declared in `needs:`. Deploys services in dependency order.

## Deploy via profiles (infra repo)

```bash
klight up <profile> --env alice      # bring up profile (supports includes:)
klight down <profile> --env alice    # scale down
klight profile list                  # list all profiles
klight profile status <name> --env alice
```

## Service operations

```bash
klight ps --env alice                  # pretty status table
klight unready --env alice             # broken services + fix hint
klight logs <service> --env alice [-f] [--tail N] [--since 30m]
klight open <service> --env alice      # port-forward + open browser
klight exec <service> --env alice -- sh  # exec into pod by service name
klight service restart <service> --env alice
klight service scale <service> --env alice --replicas 2
klight service deploy <service> --env alice --image registry/svc:tag
```

## Database

```bash
klight db connect postgres --env alice [--db my_db]   # open psql
klight db connect redis --env alice                   # open redis-cli
klight db query --env alice --db my_db "SELECT count(*) FROM users"
klight db migrate <service> --env alice               # run migration job
```

## Local development

```bash
klight local setup [--cpus 4] [--memory 6144]    # start minikube klight-demo
klight local build-load <service> --path ./dir   # docker build + minikube image load
klight local status                              # minikube status + loaded images
klight preflight [repos...] [--fix]              # check image availability
klight watch <service> --env alice --path ./dir  # hot reload on file change
```

## Init and generate

```bash
klight init ./my-service            # scan + generate klight.yaml (interactive)
klight init ./my-service --yes      # non-interactive (use detected defaults)
klight init ./my-service --force    # overwrite existing klight.yaml
```

## UI

```bash
klight ui                    # open web dashboard at localhost:7700
klight ui --port 8080        # custom port
klight ui --no-browser       # start server without opening browser
```

## Vault secrets

```bash
klight vault init --env alice            # initialize Vault in the namespace
klight vault seed --env alice --file manifests/env/secrets/global.env
klight vault seed --env alice --from-ci-env DB_PASS API_KEY
```

## Environment variables used by klight

| Variable | Description |
|---|---|
| `KUBECONFIG` | kubectl config path |
| `KLIGHT_MANIFESTS_DIR` | Override manifests directory |
| `KLIGHT_CONFIG` | Override klight.toml path |
| `KLIGHT_SENTINEL_IMAGE` | Sentinel image name |
