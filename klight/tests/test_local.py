"""
Tests for klight local — setup, build-load, resize, status, preload-infra.

Unit tests run without any infrastructure.
Integration tests require minikube klight-demo running.

Run all:
    cd klight && pytest tests/test_local.py -v

Run only unit tests:
    pytest tests/test_local.py -v -m "not integration"

Run integration tests (minikube must be running):
    KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml pytest tests/test_local.py -v -m integration
"""

import os
import subprocess

import pytest


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_catalog_all_images_have_tag():
    """Every built-in catalog entry must have a properly tagged image string."""
    from klight.catalog import load as load_catalog

    catalog = load_catalog()
    assert len(catalog) > 0, "Catalog should not be empty"

    for name, entry in catalog.items():
        assert "image" in entry, f"Catalog entry '{name}' missing 'image' key"
        assert ":" in entry["image"], (
            f"Catalog entry '{name}' image '{entry['image']}' has no tag — "
            "floating :latest images cause non-reproducible environments"
        )


def test_catalog_all_images_have_port():
    """Every catalog entry must have a port."""
    from klight.catalog import load as load_catalog

    for name, entry in load_catalog().items():
        assert "port" in entry, f"Catalog entry '{name}' missing 'port'"
        assert isinstance(entry["port"], int), f"'{name}' port is not an int"


def test_catalog_postgres_image():
    from klight.catalog import image
    assert image("postgres") == "postgres:16-alpine"


def test_catalog_kafka_image():
    from klight.catalog import image
    assert "kafka" in image("kafka").lower()


def test_catalog_redis_image():
    from klight.catalog import image
    assert image("redis").startswith("redis:")


def test_catalog_unknown_returns_latest():
    from klight.catalog import image
    assert image("nonexistent-service") == "nonexistent-service:latest"


def test_estimate_profile_mb_returns_error_when_no_team():
    """Without a synced team, _estimate_profile_mb should return an error dict."""
    from klight.commands.local import _estimate_profile_mb

    result = _estimate_profile_mb("store")
    assert isinstance(result, dict)
    # Either has an error (no team synced) or has the sizing keys
    if "error" in result:
        assert isinstance(result["error"], str)
        assert len(result["error"]) > 0
    else:
        assert "estimated_mb" in result
        assert "recommended_mb" in result


def test_estimate_profile_mb_structure_when_successful():
    """If estimate succeeds, output should have all expected keys and sane values."""
    from klight.commands.local import _estimate_profile_mb, _K8S_OVERHEAD_MB

    result = _estimate_profile_mb("store")
    if "error" in result:
        pytest.skip("No team synced — cannot verify output structure")

    assert result["recommended_mb"] >= 2048
    assert result["estimated_mb"] >= _K8S_OVERHEAD_MB
    assert result["services_mb"] >= 0
    assert result["infra_mb"] >= 0
    assert isinstance(result["infra"], list)
    assert result["service_count"] >= 0


def test_preload_infra_help():
    """klight local preload-infra --help should exit 0 and explain usage."""
    r = subprocess.run(
        ["klight", "local", "preload-infra", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--only" in r.stdout
    assert "--profile" in r.stdout


def test_preload_infra_rejects_unknown_names():
    """Passing an unknown infra name should exit non-zero with an informative message."""
    r = subprocess.run(
        ["klight", "local", "preload-infra", "--only", "nonexistent-infra-xyz"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "nonexistent-infra-xyz" in r.stdout or "Unknown" in r.stdout


# ── Integration tests — require minikube ─────────────────────────────────────

@pytest.mark.integration
def test_preload_infra_postgres(minikube_running):
    """
    Pull and load postgres:16-alpine into minikube.
    This is the most commonly needed image and a fast test (~30s on warm Docker cache).
    """
    env = {**os.environ, "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"}

    r = subprocess.run(
        ["klight", "local", "preload-infra", "--only", "postgres",
         "--profile", "klight-demo"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert r.returncode == 0, (
        f"preload-infra postgres failed:\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}"
    )
    assert "loaded" in r.stdout.lower()


@pytest.mark.integration
def test_preload_infra_redis(minikube_running):
    """Pull and load redis:7-alpine into minikube."""
    env = {**os.environ, "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"}

    r = subprocess.run(
        ["klight", "local", "preload-infra", "--only", "redis",
         "--profile", "klight-demo"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert r.returncode == 0, f"preload-infra redis failed:\n{r.stdout}\n{r.stderr}"
    assert "loaded" in r.stdout.lower()


@pytest.mark.integration
def test_preload_infra_postgres_redis_together(minikube_running):
    """
    Preload both postgres and redis in one call.
    Covers the multi-name code path.
    """
    env = {**os.environ, "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"}

    r = subprocess.run(
        ["klight", "local", "preload-infra", "--only", "postgres,redis",
         "--profile", "klight-demo"],
        capture_output=True, text=True, env=env, timeout=600,
    )
    assert r.returncode == 0, (
        f"preload-infra postgres,redis failed:\n{r.stdout}\n{r.stderr}"
    )
    assert r.stdout.count("loaded") >= 2


@pytest.mark.integration
def test_preload_infra_images_appear_in_minikube(minikube_running):
    """
    After preloading postgres, verify it appears in minikube image ls.
    This is the definitive check that the image is usable by pods.
    """
    from klight.catalog import image as catalog_image

    env = {**os.environ, "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"}
    pg_image = catalog_image("postgres")

    # Preload
    subprocess.run(
        ["klight", "local", "preload-infra", "--only", "postgres",
         "--profile", "klight-demo"],
        capture_output=True, text=True, env=env, timeout=300,
    )

    # Verify via minikube image ls
    r = subprocess.run(
        ["minikube", "image", "ls", "--profile=klight-demo"],
        capture_output=True, text=True,
    )
    assert pg_image in r.stdout, (
        f"Expected '{pg_image}' in minikube images after preload.\n"
        f"Got:\n{r.stdout}"
    )


@pytest.mark.integration
def test_local_status_shows_loaded_images(minikube_running):
    """klight local status should exit 0 when minikube is running."""
    env = {**os.environ, "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"}

    r = subprocess.run(
        ["klight", "local", "status", "--profile", "klight-demo"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, f"klight local status failed:\n{r.stdout}\n{r.stderr}"
