"""
Shared fixtures for klight pytest tests.

Environment variables:
  KUBECONFIG                  — path to kubeconfig (default: /tmp/klight-demo-kubeconfig.yaml)
  KLIGHT_TEST_SERVICES_DIR    — path to services with real Dockerfiles and klight.yaml files
                                (default: /Users/dany/dev/klight-suite-test/services)
  KLIGHT_MINIKUBE_PROFILE     — minikube profile to use (default: klight-demo)
"""

import os
import subprocess
from pathlib import Path

import pytest

KUBECONFIG = os.environ.get("KUBECONFIG", "/tmp/klight-demo-kubeconfig.yaml")
SERVICES_DIR = Path(
    os.environ.get("KLIGHT_TEST_SERVICES_DIR", "/Users/dany/dev/klight-suite-test/services")
)
MINIKUBE_PROFILE = os.environ.get("KLIGHT_MINIKUBE_PROFILE", "klight-demo")


def _minikube_running() -> bool:
    r = subprocess.run(
        ["minikube", "status", "-p", MINIKUBE_PROFILE, "-o", "json"],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0 and '"Running"' in r.stdout


def _env_running(env_name: str) -> bool:
    env = {**os.environ, "KUBECONFIG": KUBECONFIG}
    r = subprocess.run(
        ["kubectl", "get", "namespace", f"env-{env_name}"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    return r.returncode == 0


def _deployment_running(service: str, env_name: str) -> bool:
    env = {**os.environ, "KUBECONFIG": KUBECONFIG}
    r = subprocess.run(
        ["kubectl", "get", "deployment", service, "-n", f"env-{env_name}",
         "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    return r.returncode == 0 and r.stdout.strip() not in ("", "0")


@pytest.fixture(scope="session")
def minikube_running():
    if not _minikube_running():
        pytest.skip(f"minikube profile '{MINIKUBE_PROFILE}' not running — run: klight local setup")


@pytest.fixture(scope="session")
def env_dev_running(minikube_running):
    if not _env_running("dev"):
        pytest.skip(
            "env-dev not running — run: "
            "klight from-repos ./klight-suite-test/services/* --env dev"
        )


@pytest.fixture(scope="session")
def inventory_api_running(env_dev_running):
    if not _deployment_running("inventory-api", "dev"):
        pytest.skip("inventory-api not ready in env-dev")


@pytest.fixture(scope="session")
def inventory_api_path() -> Path:
    p = SERVICES_DIR / "inventory-api"
    if not p.exists():
        pytest.skip(f"inventory-api service dir not found: {p}")
    return p


@pytest.fixture(scope="session")
def store_api_path() -> Path:
    p = SERVICES_DIR / "store-api"
    if not p.exists():
        pytest.skip(f"store-api service dir not found: {p}")
    return p
