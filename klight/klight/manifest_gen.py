"""
Generates K8s manifest dicts from KlightConfig.
No files written — manifests applied directly via kubectl apply -f <(echo json).
This is how klight works without requiring a separate infra repo.
"""

from __future__ import annotations
import hashlib
import json
from typing import Any
from klight.schema import KlightConfig

SENTINEL_IMAGE = "klight-sentinel:latest"


def _pull_policy(image: str) -> str:
    """Never for local builds (:local tag), IfNotPresent for registry images."""
    if not image or image.endswith(":local"):
        return "Never"
    return "IfNotPresent"


def _env_from(cfg: KlightConfig) -> list[dict]:
    """envFrom sources: global config/secrets, per-service config, and
    (when declared) a per-service Secret materialized from secrets:.

    The per-service secretRef is marked optional so the service still starts in
    "mock mode" before any secret is set via `klight secrets set`.
    """
    sources = [
        {"configMapRef": {"name": "klight-global-config"}},
        {"configMapRef": {"name": f"{cfg.name}-config"}},
        {"secretRef": {"name": "klight-global-secrets"}},
    ]
    if getattr(cfg, "secrets", None):
        sources.append({"secretRef": {"name": cfg.secret_name(), "optional": True}})
    return sources


def _probe(cfg: KlightConfig, initial: int, period: int, failure_threshold: int = 3) -> dict:
    """HTTP probe when a health path is set; TCP probe otherwise (e.g. gRPC)."""
    if cfg.health:
        action = {"httpGet": {"path": cfg.health, "port": cfg.port}}
    else:
        action = {"tcpSocket": {"port": cfg.port}}
    return {**action, "initialDelaySeconds": initial, "periodSeconds": period, "failureThreshold": failure_threshold}


def _config_hash(cfg: KlightConfig) -> str:
    """Hash of env/secrets declarations so pod template changes when config
    changes, forcing a rollout (ConfigMap/Secret edits alone don't restart pods)."""
    payload = json.dumps({"env": cfg.env, "secrets": getattr(cfg, "secrets", None)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


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
                "metadata": {
                    "labels": {"app": cfg.name, "klight.service": cfg.name},
                    "annotations": {"klight.io/config-hash": _config_hash(cfg)},
                },
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
                            "envFrom": _env_from(cfg),
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "768Mi"},
                                "limits": {"memory": "1536Mi"},
                            },
                            # JVM services (Spring Boot etc.) can take minutes to start,
                            # especially when they retry/timeout against unreachable external
                            # deps. startupProbe owns that grace period (up to 10 min here);
                            # readiness/liveness only kick in once startup succeeds once.
                            "startupProbe": _probe(cfg, initial=10, period=10, failure_threshold=60),
                            "readinessProbe": _probe(cfg, initial=0, period=10, failure_threshold=3),
                            "livenessProbe": _probe(cfg, initial=0, period=15, failure_threshold=6),
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
                            "envFrom": _env_from(cfg),
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
