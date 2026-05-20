# Local vs Remote

klight works the same whether running against a local minikube or a remote cluster. The only difference is the kubectl context.

## Configuring targets

Create `klight.toml` at your infra repo root:

```toml
[targets]
default = "local"
local   = "klight-demo"        # minikube profile
remote  = "company-dev"        # kubectl context name
```

## Switching targets

```bash
klight use local     # → kubectl config use-context klight-demo
klight use remote    # → kubectl config use-context company-dev
klight target        # show current target + all configured targets
```

All `klight` commands run against whatever `kubectl context` is active.

## Setting up local (minikube)

```bash
klight local setup [--cpus 4] [--memory 6144]
```

Creates minikube profile `klight-demo`. Does not affect other clusters.

## Connecting to a remote cluster

```bash
# From a kubeconfig file your DevOps team provides:
klight connect --kubeconfig ~/Downloads/company-dev.yaml

# From a URL + token:
klight connect --url https://k8s.dev.mycompany.com --token eyJhbGciOiJ...
```

## Critical: multiple contexts on the same machine

If you work with SoFi's Kraken or any other production cluster, your `~/.kube/config` will have multiple contexts. **Always check before deploying:**

```bash
klight target           # show current context
kubectl config current-context
```

Or use an isolated kubeconfig for klight:
```bash
export KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml
```

The `klight.toml` `[targets]` section defines safe named targets. `klight use local` always points to minikube, never to production.

## Behavior differences

| | Local (minikube) | Remote (cluster) |
|---|---|---|
| Image source | `minikube image load` | Container registry pull |
| `imagePullPolicy` | `Never` | `IfNotPresent` or `Always` |
| Storage | hostPath PVCs | Cloud storage class |
| Infra images | Must be pre-loaded | Auto-pulled from Docker Hub |
| Port-forward | Works directly | Works (tunneled locally) |

## Image strategy by target

For **local**: build with `klight local build-load`, use `imagePullPolicy: Never`.

For **remote**: CI builds and pushes to a registry. klight uses the image tag from klight.yaml or `--image` flag. `imagePullPolicy: IfNotPresent`.

The `klight.toml` `[images]` section sets the default registry:
```toml
[images]
registry = "ghcr.io/mycompany"
```

Then `image: my-api:main` resolves to `ghcr.io/mycompany/my-api:main` on remote.
