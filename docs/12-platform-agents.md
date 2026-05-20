# Platform Agents (Datadog, Fluent Bit, etc.)

## DaemonSet annotations — safe in klight

Most observability agents use DaemonSets with pod annotations. If the DaemonSet isn't running in the klight environment, annotations are simply ignored — the pod starts normally.

```yaml
# Pod spec — these annotations do nothing if Datadog DaemonSet isn't present
metadata:
  annotations:
    ad.datadoghq.com/my-api.check_names: '["openmetrics"]'
```

This is the recommended pattern.

## Sidecar in pod spec — can fail

If an agent is baked as a sidecar container that reads from a missing Secret:

```yaml
containers:
- name: my-api
- name: datadog-agent           # ← will fail if Secret not found
  env:
  - name: DD_API_KEY
    valueFrom:
      secretKeyRef:
        name: datadog-secret    # ← doesn't exist in local env
```

### Fix: overlays/local/ strips sidecars

```yaml
# manifests/services/my-api/overlays/local/kustomization.yaml
resources: [../../base]
patches:
- patch: |-
    - op: remove
      path: /spec/template/spec/containers/1
  target:
    kind: Deployment
    name: my-api
```

## For klight-generated manifests

klight-generated manifests don't include platform sidecars by design. Agents run at the cluster level (DaemonSets), not per-service.

## Recommended architecture

- **Datadog metrics**: DaemonSet + pod annotations
- **Logs**: Fluent Bit DaemonSet (reads stdout from all namespaces)
- **Traces (APM)**: `DD_AGENT_HOST` env var → agent DaemonSet (graceful if unreachable)
- **Vault secrets**: klight Vault StatefulSet in namespace (for dev)

One DaemonSet agent per cluster node = no per-dev cost multiplier.
