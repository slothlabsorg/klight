"""
Generates K8s manifest dicts from KlightConfig.
No files written — manifests applied directly via kubectl apply -f <(echo json).
This is how klight works without requiring a separate infra repo.
"""

from __future__ import annotations
from typing import Any
from klight.schema import KlightConfig

SENTINEL_IMAGE = "klight-sentinel:latest"


def _pull_policy(image: str) -> str:
    """Never for local builds (:local tag), IfNotPresent for registry images."""
    if not image or image.endswith(":local"):
        return "Never"
    return "IfNotPresent"


def deployment(cfg: KlightConfig) -> dict[str, Any]:
    sentinel_deps = cfg.sentinel_deps()
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": cfg.name},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": cfg.name}},
            "template": {
                "metadata": {"labels": {"app": cfg.name, "klight.service": cfg.name}},
                "spec": {
                    "initContainers": [
                        {
                            "name": "sentinel",
                            "image": SENTINEL_IMAGE,
                            "imagePullPolicy": "Never",
                            "env": [
                                {"name": "STARTUP_DEPENDENCIES", "value": sentinel_deps},
                                {"name": "SENTINEL_TIMEOUT", "value": "180"},
                            ],
                        }
                    ] if sentinel_deps else [],
                    "containers": [
                        {
                            "name": cfg.name,
                            "image": cfg.effective_image(),
                            "imagePullPolicy": _pull_policy(cfg.effective_image()),
                            "ports": [{"containerPort": cfg.port}],
                            "envFrom": [
                                {"configMapRef": {"name": "klight-global-config"}},
                                {"configMapRef": {"name": f"{cfg.name}-config"}},
                                {"secretRef": {"name": "klight-global-secrets"}},
                            ],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"memory": "256Mi"},
                            },
                            "readinessProbe": {
                                "httpGet": {"path": cfg.health, "port": cfg.port},
                                "initialDelaySeconds": 10,
                                "periodSeconds": 5,
                            },
                            "livenessProbe": {
                                "httpGet": {"path": cfg.health, "port": cfg.port},
                                "initialDelaySeconds": 20,
                                "periodSeconds": 10,
                            },
                        }
                    ],
                },
            },
        },
    }


def service(cfg: KlightConfig) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": cfg.name},
        "spec": {
            "selector": {"app": cfg.name},
            "ports": [{"port": cfg.port, "targetPort": cfg.port}],
        },
    }


def configmap(cfg: KlightConfig) -> dict[str, Any]:
    """ConfigMap with the service's own env vars (from klight.yaml env: section)."""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{cfg.name}-config"},
        "data": {k: str(v) for k, v in cfg.env.items()},
    }


def migration_job(cfg: KlightConfig) -> dict[str, Any] | None:
    if not cfg.migration:
        return None

    infra_ports = []
    for need in cfg.needs:
        need_name = need if isinstance(need, str) else need.name
        from klight.catalog import port as catalog_port, is_known
        if is_known(need_name):
            infra_ports.append(f"{need_name}:{catalog_port(need_name)}")

    sentinel_deps = " ".join(infra_ports) if infra_ports else ""

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": f"{cfg.name}-migrate"},
        "spec": {
            "backoffLimit": 3,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "initContainers": [
                        {
                            "name": "sentinel",
                            "image": SENTINEL_IMAGE,
                            "imagePullPolicy": "Never",
                            "env": [
                                {"name": "STARTUP_DEPENDENCIES", "value": sentinel_deps},
                                {"name": "SENTINEL_TIMEOUT", "value": "120"},
                            ],
                        }
                    ] if sentinel_deps else [],
                    "containers": [
                        {
                            "name": "migrate",
                            "image": cfg.effective_image(),
                            "imagePullPolicy": _pull_policy(cfg.effective_image()),
                            "command": cfg.migration.command,
                            "envFrom": [
                                {"configMapRef": {"name": "klight-global-config"}},
                                {"configMapRef": {"name": f"{cfg.name}-config"}},
                                {"secretRef": {"name": "klight-global-secrets"}},
                            ],
                        }
                    ],
                }
            },
        },
    }


def all_manifests(cfg: KlightConfig) -> list[dict[str, Any]]:
    """All K8s manifests for a service, in apply order."""
    manifests = [configmap(cfg), service(cfg), deployment(cfg)]
    job = migration_job(cfg)
    if job:
        manifests.insert(0, job)  # migrations first
    return manifests


def kubectl_apply_manifest(manifest: dict, namespace: str) -> None:
    """Apply a manifest dict to a namespace via kubectl."""
    from klight import kubectl as k
    k.apply_manifest_dict(manifest, namespace)


def infra_manifest(name: str, image: str, port: int, ns: str) -> list[dict]:
    """Generate StatefulSet + Service manifests for an infra dependency."""
    from klight.catalog import load as load_catalog
    catalog = load_catalog()
    entry = catalog.get(name, {})
    img = entry.get("image", image)
    p = entry.get("port", port)
    env_vars = entry.get("env", {})
    env_list = [{"name": k, "value": str(v)} for k, v in env_vars.items()]

    sts: dict[str, Any] = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": name},
        "spec": {
            "serviceName": name,
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "containers": [{
                        "name": name,
                        "image": img,
                        "ports": [{"containerPort": p}],
                        "env": env_list,
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"memory": "512Mi"},
                        },
                    }],
                },
            },
        },
    }
    svc: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {
            "selector": {"app": name},
            "ports": [{"port": p, "targetPort": p}],
        },
    }
    return [svc, sts]


def has_own_manifest(cfg) -> bool:
    """True if the service has its own K8s manifests (deploy/ or manifest: field)."""
    if cfg.manifest:
        return True
    if cfg.repo_path:
        # Auto-detect deploy/ folder in repo
        from pathlib import Path
        deploy = Path(cfg.repo_path) / 'deploy'
        if deploy.exists():
            for overlay in ['overlays/dev', 'overlays/local', 'base']:
                if (deploy / overlay).exists():
                    return True
    return False


def resolve_manifest_path(cfg) -> str | None:
    """Return the kustomize path to apply for a service with existing manifests."""
    if cfg.manifest:
        if cfg.repo_path:
            from pathlib import Path
            p = Path(cfg.repo_path) / cfg.manifest
            return str(p.resolve()) if p.exists() else cfg.manifest
        return cfg.manifest
    if cfg.repo_path:
        from pathlib import Path
        deploy = Path(cfg.repo_path) / 'deploy'
        for overlay in ['overlays/dev', 'overlays/local', 'base']:
            candidate = deploy / overlay
            if candidate.exists():
                return str(candidate.resolve())
    return None


def sentinel_patch(cfg, namespace: str) -> None:
    """
    Inject sentinel initContainer into an existing Deployment via kubectl patch.
    Called AFTER applying existing manifests. The service's deploy/ stays clean.

    The service developer never writes sentinel — klight adds it transparently.
    """
    deps = cfg.sentinel_deps()
    if not deps:
        return  # no needs declared → nothing to inject

    import json
    import subprocess

    patch = {
        "spec": {
            "template": {
                "spec": {
                    "initContainers": [
                        {
                            "name": "sentinel",
                            "image": "klight-sentinel:latest",
                            "imagePullPolicy": "Never",
                            "env": [
                                {"name": "STARTUP_DEPENDENCIES", "value": deps},
                                {"name": "SENTINEL_TIMEOUT", "value": "180"},
                            ],
                        }
                    ]
                }
            }
        }
    }

    subprocess.run(
        ["kubectl", "patch", "deployment", cfg.name,
         "-n", namespace,
         "--type=strategic",
         f"--patch={json.dumps(patch)}"],
        capture_output=True,
    )
