"""
K8s YAML scanner — reads all Kubernetes manifests from a directory tree,
extracts services, infra dependencies, env vars, and image info.

Works with any structure: Kustomize, Helm (rendered), bare YAML, mixed.
Does not need to know the folder structure ahead of time.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any
import yaml


INFRA_IMAGES = {
    "postgres": ["postgres:", "bitnami/postgresql"],
    "mysql": ["mysql:", "bitnami/mysql"],
    "mongodb": ["mongo:", "bitnami/mongodb"],
    "redis": ["redis:", "bitnami/redis"],
    "kafka": ["kafka:", "apache/kafka", "bitnami/kafka", "confluentinc/cp-kafka"],
    "rabbitmq": ["rabbitmq:", "bitnami/rabbitmq"],
    "elasticsearch": ["elasticsearch:", "docker.elastic.co/elasticsearch"],
    "localstack": ["localstack/localstack"],
    "vault": ["hashicorp/vault", "vault:"],
    "ollama": ["ollama/ollama"],
}

CI_IMAGE_PATTERNS = [
    r'image:\s+([^\s]+)',                    # YAML inline
    r'docker\s+build.*?-t\s+([^\s]+)',       # docker build -t
    r'docker\.io/([^\s]+)',
    r'ghcr\.io/([^\s]+)',
    r'(\d+\.dkr\.ecr\.[^\s]+)',              # ECR
    r'registry\.gitlab\.com/([^\s]+)',
]


class ScannedService:
    def __init__(self, name: str):
        self.name = name
        self.port: int | None = None
        self.health: str = "/health"
        self.image: str = ""
        self.manifest_path: str = ""       # path to the K8s manifest dir
        self.needs: list[str] = []         # infra detected
        self.env: dict[str, str] = {}      # env vars from ConfigMaps
        self.has_migration: bool = False
        self.framework: str = ""           # Spring Boot, FastAPI, etc.


class ScanResult:
    def __init__(self):
        self.services: dict[str, ScannedService] = {}
        self.infra_detected: list[str] = []          # postgres, kafka, etc.
        self.raw_deployments: list[dict] = []
        self.raw_configmaps: dict[str, dict] = {}    # name → data
        self.raw_statefulsets: list[dict] = []


def scan_directory(path: Path) -> ScanResult:
    """
    Read all YAML files in path recursively.
    Extract K8s resources and build a ScanResult.
    """
    result = ScanResult()

    # Load all YAMLs
    all_docs: list[dict] = []
    for yaml_file in sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")):
        # Skip common non-K8s files
        if any(part.startswith(".") for part in yaml_file.parts):
            continue
        if yaml_file.name in ("klight.yaml", "klight-team.yaml", "klight-catalog.yaml",
                               "docker-compose.yml", "docker-compose.yaml"):
            continue
        try:
            with open(yaml_file) as f:
                for doc in yaml.safe_load_all(f):
                    if isinstance(doc, dict) and doc.get("kind"):
                        doc["_source_file"] = str(yaml_file)
                        all_docs.append(doc)
        except Exception:
            continue

    # Process by kind
    for doc in all_docs:
        kind = doc.get("kind", "")
        if kind == "Deployment":
            _process_deployment(doc, result)
        elif kind == "StatefulSet":
            _process_statefulset(doc, result)
        elif kind == "ConfigMap":
            _process_configmap(doc, result)
        elif kind == "Job":
            _process_job(doc, result)

    # Match ConfigMaps to Services
    _correlate_envs(result)

    return result


def _process_deployment(doc: dict, result: ScanResult) -> None:
    name = doc.get("metadata", {}).get("name", "")
    if not name:
        return

    svc = result.services.setdefault(name, ScannedService(name))
    svc.manifest_path = str(Path(doc["_source_file"]).parent)

    spec = doc.get("spec", {}).get("template", {}).get("spec", {})
    containers = spec.get("containers", [])

    for container in containers:
        if container.get("name") == name or not svc.image:
            img = container.get("image", "")
            if img and not _is_infra_image(img):
                svc.image = img

            # Port
            for port in container.get("ports", []):
                cp = port.get("containerPort")
                if cp and not svc.port:
                    svc.port = int(cp)

            # Health from probes
            probe = container.get("readinessProbe", container.get("livenessProbe", {}))
            http = probe.get("httpGet", {})
            if http.get("path"):
                svc.health = http["path"]

            # Detect infra from env
            for env_entry in container.get("env", []):
                v = str(env_entry.get("value", ""))
                _detect_infra_from_value(v, svc)

    result.raw_deployments.append(doc)


def _process_statefulset(doc: dict, result: ScanResult) -> None:
    name = doc.get("metadata", {}).get("name", "")
    if not name:
        return

    spec = doc.get("spec", {}).get("template", {}).get("spec", {})
    for container in spec.get("containers", []):
        img = container.get("image", "")
        infra = _image_to_infra(img)
        if infra and infra not in result.infra_detected:
            result.infra_detected.append(infra)

    result.raw_statefulsets.append(doc)


def _process_configmap(doc: dict, result: ScanResult) -> None:
    name = doc.get("metadata", {}).get("name", "")
    data = doc.get("data", {}) or {}
    result.raw_configmaps[name] = data


def _process_job(doc: dict, result: ScanResult) -> None:
    name = doc.get("metadata", {}).get("name", "")
    if name and ("migrate" in name or "migration" in name or "dbinit" in name):
        # Find which service this migration is for
        svc_name = name.replace("-dbmigrate", "").replace("-migrate", "").replace("-migration", "")
        if svc_name in result.services:
            result.services[svc_name].has_migration = True


def _correlate_envs(result: ScanResult) -> None:
    """Match ConfigMaps to services by name convention."""
    for svc_name, svc in result.services.items():
        # Look for ConfigMaps named {svc}-config or {svc}-configmap
        for cm_name, cm_data in result.raw_configmaps.items():
            if svc_name in cm_name:
                for key, value in cm_data.items():
                    if key not in svc.env:
                        svc.env[key] = str(value) if value else ""
                    _detect_infra_from_value(str(value or ""), svc)

        # Infer needs from infra_detected
        for infra in result.infra_detected:
            if infra not in svc.needs:
                svc.needs.append(infra)


def _is_infra_image(image: str) -> bool:
    return any(
        any(pattern in image for pattern in patterns)
        for patterns in INFRA_IMAGES.values()
    )


def _image_to_infra(image: str) -> str | None:
    for infra, patterns in INFRA_IMAGES.items():
        if any(p in image for p in patterns):
            return infra
    return None


def _detect_infra_from_value(value: str, svc: ScannedService) -> None:
    """Look for infra hostnames in env var values."""
    for infra in INFRA_IMAGES:
        if infra in value.lower() and infra not in svc.needs:
            svc.needs.append(infra)


def scan_ci_files(path: Path) -> dict[str, str]:
    """
    Scan CI files to find Docker image names.
    Returns {service_name: image_tag}
    """
    images = {}
    ci_files = [
        path / ".github" / "workflows",
        path / ".gitlab-ci.yml",
        path / "Jenkinsfile",
        path / ".circleci" / "config.yml",
    ]

    all_ci_content = ""
    for ci_path in ci_files:
        if ci_path.is_file():
            all_ci_content += ci_path.read_text(errors="ignore")
        elif ci_path.is_dir():
            for f in ci_path.glob("*.yml"):
                all_ci_content += f.read_text(errors="ignore")

    for pattern in CI_IMAGE_PATTERNS:
        for match in re.finditer(pattern, all_ci_content):
            img = match.group(1).strip().strip('"').strip("'")
            if ":" in img:
                name = img.split("/")[-1].split(":")[0]
                if name:
                    images[name] = img

    return images
