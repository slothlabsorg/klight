"""Thin wrapper around kubectl subprocess calls."""

import subprocess
import json
import os
from pathlib import Path
from typing import Any


def run(args: list[str], capture: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    cmd = ["kubectl"] + args
    kubeconfig = os.environ.get("KUBECONFIG")
    if kubeconfig:
        cmd = ["kubectl", f"--kubeconfig={kubeconfig}"] + args
    return subprocess.run(cmd, capture_output=capture, text=True, check=check)


def run_json(args: list[str]) -> Any:
    result = run(args + ["-o", "json"])
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def apply_kustomize(path: str | Path, namespace: str) -> subprocess.CompletedProcess:
    return run(["apply", "-k", str(path), "-n", namespace], capture=False)


def apply_manifest_dict(manifest: dict, namespace: str) -> subprocess.CompletedProcess:
    """Apply a manifest dict directly via kubectl apply -f -."""
    import tempfile
    import yaml as _yaml
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        _yaml.dump(manifest, f)
        tmp = f.name
    result = run(["apply", "-f", tmp, "-n", namespace], capture=False)
    Path(tmp).unlink(missing_ok=True)
    return result


def namespace_exists(name: str) -> bool:
    result = run(["get", "namespace", name])
    return result.returncode == 0


def get_manifests_dir() -> Path:
    env_override = os.environ.get("KLIGHT_MANIFESTS_DIR")
    if env_override:
        return Path(env_override)
    # Walk up from this file to find manifests/
    here = Path(__file__).parent
    for parent in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        candidate = parent / "manifests"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "Cannot find manifests/ directory. Set KLIGHT_MANIFESTS_DIR env var."
    )
