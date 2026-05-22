"""
Tests for klight watch — hot reload: file watching, build, load, restart.

Unit tests run without any infrastructure.
Integration tests require minikube + env-dev with inventory-api deployed.

Run all:
    cd klight && pytest tests/test_watch.py -v

Run only unit tests:
    pytest tests/test_watch.py -v -m "not integration"

Run integration tests:
    KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml pytest tests/test_watch.py -v -m integration
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import yaml


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_get_mtimes_tracks_file():
    from klight.commands.watch import _get_mtimes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        f = p / "app.py"
        f.write_text("version = 1")

        mtimes = _get_mtimes([p])
        assert str(f) in mtimes


def test_get_mtimes_detects_modification():
    from klight.commands.watch import _get_mtimes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        f = p / "app.py"
        f.write_text("version = 1")

        mtimes1 = _get_mtimes([p])
        time.sleep(0.05)
        f.write_text("version = 2")
        mtimes2 = _get_mtimes([p])

        changed = {k for k, mt in mtimes2.items() if mtimes1.get(k) != mt}
        assert str(f) in changed, "Modified file should appear in changed set"


def test_get_mtimes_detects_new_file():
    from klight.commands.watch import _get_mtimes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "existing.py").write_text("x = 1")

        mtimes1 = _get_mtimes([p])
        time.sleep(0.01)
        new_file = p / "new.py"
        new_file.write_text("y = 2")
        mtimes2 = _get_mtimes([p])

        changed = {k for k, mt in mtimes2.items() if mtimes1.get(k) != mt}
        assert str(new_file) in changed


def test_get_mtimes_ignores_hidden_dirs():
    from klight.commands.watch import _get_mtimes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / ".git").mkdir()
        (p / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (p / "app.py").write_text("code")

        mtimes = _get_mtimes([p])
        hidden = [k for k in mtimes if ".git" in k]
        assert hidden == [], f"Should not watch .git files, got: {hidden}"


def test_get_mtimes_ignores_pycache():
    from klight.commands.watch import _get_mtimes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "__pycache__").mkdir()
        (p / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"\x00\x01\x02")
        (p / "app.py").write_text("code")

        mtimes = _get_mtimes([p])
        cached = [k for k in mtimes if "__pycache__" in k]
        assert cached == [], f"Should not watch __pycache__, got: {cached}"


def test_get_mtimes_ignores_node_modules():
    from klight.commands.watch import _get_mtimes

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "node_modules").mkdir()
        (p / "node_modules" / "lodash.js").write_text("module.exports = {}")
        (p / "index.js").write_text("const x = require('lodash')")

        mtimes = _get_mtimes([p])
        nm = [k for k in mtimes if "node_modules" in k]
        assert nm == []


def test_get_mtimes_handles_missing_path():
    from klight.commands.watch import _get_mtimes

    mtimes = _get_mtimes([Path("/nonexistent/path/xyz123")])
    assert mtimes == {}


def test_get_mtimes_handles_single_file():
    from klight.commands.watch import _get_mtimes

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        path = Path(f.name)
        path.write_text("x = 1")

    try:
        mtimes = _get_mtimes([path])
        assert str(path) in mtimes
    finally:
        path.unlink(missing_ok=True)


def test_build_image_no_dockerfile(tmp_path):
    """_build_image returns False when no Dockerfile and no custom build command."""
    from klight.commands.watch import _build_image
    from klight.schema import KlightConfig

    (tmp_path / "klight.yaml").write_text(
        yaml.dump({"name": "test-svc", "port": 8080})
    )
    cfg = KlightConfig.from_file(tmp_path / "klight.yaml")
    result = _build_image(cfg, tmp_path)
    assert result is False


def test_build_image_with_custom_command_failure(tmp_path):
    """_build_image returns False when the custom build command fails."""
    from klight.commands.watch import _build_image
    from klight.schema import KlightConfig

    (tmp_path / "klight.yaml").write_text(
        yaml.dump({
            "name": "test-svc",
            "port": 8080,
            "build": {"command": "exit 1", "context": "."},
        })
    )
    cfg = KlightConfig.from_file(tmp_path / "klight.yaml")
    result = _build_image(cfg, tmp_path)
    assert result is False


def test_watch_cmd_help():
    """klight watch --help should exit 0 and mention key flags."""
    r = subprocess.run(
        ["klight", "watch", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--env" in r.stdout
    assert "--initial-build" in r.stdout or "initial" in r.stdout.lower()


# ── Integration tests — require minikube + env-dev ────────────────────────────

@pytest.mark.integration
def test_watch_build_cycle_inventory_api(minikube_running, inventory_api_running, inventory_api_path):
    """
    Full build cycle using inventory-api from klight-suite-test.
    Verifies: docker build succeeds, minikube image load succeeds.
    """
    from klight.commands.watch import _build_image, _load_to_minikube
    from klight.schema import KlightConfig

    cfg = KlightConfig.from_file(inventory_api_path / "klight.yaml")

    ok = _build_image(cfg, inventory_api_path)
    assert ok, "docker build of inventory-api failed"

    loaded = _load_to_minikube(cfg.effective_image(), "klight-demo")
    assert loaded, "minikube image load of inventory-api:local failed"


@pytest.mark.integration
def test_watch_file_change_triggers_rebuild(
    minikube_running, inventory_api_running, inventory_api_path, tmp_path
):
    """
    Integration test: touch a source file, confirm _get_mtimes detects it,
    and a subsequent build+load cycle completes.
    """
    from klight.commands.watch import _get_mtimes, _build_image, _load_to_minikube
    from klight.schema import KlightConfig

    cfg = KlightConfig.from_file(inventory_api_path / "klight.yaml")

    # Determine watch paths (same logic as watch.cmd)
    watch_paths = [inventory_api_path / "app"]
    watch_paths = [p for p in watch_paths if p.exists()]
    if not watch_paths:
        watch_paths = [inventory_api_path]

    # Snapshot mtimes
    mtimes1 = _get_mtimes(watch_paths)

    # Touch a source file
    target = None
    for p in watch_paths:
        py_files = list(p.rglob("*.py"))
        if py_files:
            target = py_files[0]
            break

    if target is None:
        pytest.skip("No .py file found in watch paths")

    time.sleep(0.05)
    target.touch()

    # Verify change detected
    mtimes2 = _get_mtimes(watch_paths)
    changed = {k for k, mt in mtimes2.items() if mtimes1.get(k) != mt}
    assert str(target) in changed, f"touch of {target} not detected by _get_mtimes"

    # Rebuild after change
    ok = _build_image(cfg, inventory_api_path)
    assert ok, "docker build failed after file change"

    loaded = _load_to_minikube(cfg.effective_image(), "klight-demo")
    assert loaded, "minikube image load failed after file change"


@pytest.mark.integration
def test_watch_pod_restarts_after_cycle(minikube_running, inventory_api_running, inventory_api_path):
    """
    After _run_cycle, the deployment should trigger a new rollout.
    Verify via kubectl rollout status.
    """
    from klight.commands.watch import _run_cycle
    from klight.schema import KlightConfig

    cfg = KlightConfig.from_file(inventory_api_path / "klight.yaml")
    ns = "env-dev"

    ok = _run_cycle(cfg, inventory_api_path, ns, "klight-demo")
    assert ok, "_run_cycle returned False — build or load failed"

    env = {**os.environ, "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml"}
    r = subprocess.run(
        ["kubectl", "rollout", "status", "deployment/inventory-api",
         "-n", ns, "--timeout=90s"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"rollout status failed:\n{r.stdout}\n{r.stderr}"
    assert "successfully rolled out" in r.stdout
