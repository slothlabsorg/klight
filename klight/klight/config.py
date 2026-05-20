"""
klight.toml — project-level configuration.

Lives at the root of the infra repo. Commit it.
Tells klight how to reach local and remote clusters,
what the default target is, and where images come from.

Search order:
  1. ./klight.toml (CWD)
  2. $KLIGHT_CONFIG (env var override)
"""

from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Optional

try:
    import tomllib          # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli
    except ImportError:
        tomllib = None  # type: ignore


_DEFAULT_CONFIG = {
    "targets": {
        "default": "local",
        "local": "klight-demo",
        "remote": "",
    },
    "remote": {
        "api_url": "",
        "namespace_prefix": "env",
    },
    "images": {
        "registry": "",
        "sentinel": "klight-sentinel:latest",
    },
}


def _find_config_file() -> Optional[Path]:
    override = os.environ.get("KLIGHT_CONFIG")
    if override:
        p = Path(override)
        return p if p.exists() else None
    # Walk up from CWD
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        f = candidate / "klight.toml"
        if f.exists():
            return f
    return None


def load() -> dict:
    """Load klight.toml, merging with defaults."""
    cfg = dict(_DEFAULT_CONFIG)
    for section in cfg:
        cfg[section] = dict(cfg[section])

    path = _find_config_file()
    if path and tomllib:
        try:
            with open(path, "rb") as f:
                user = tomllib.load(f)
            for section, values in user.items():
                if section in cfg:
                    cfg[section].update(values)
                else:
                    cfg[section] = values
        except Exception:
            pass

    return cfg


def current_target() -> str:
    """Return 'local' or 'remote' based on current kubectl context."""
    cfg = load()
    result = subprocess.run(
        ["kubectl", "config", "current-context"],
        capture_output=True, text=True,
    )
    ctx = result.stdout.strip()
    local_ctx = cfg["targets"].get("local", "klight-demo")
    if ctx == local_ctx:
        return "local"
    remote_ctx = cfg["targets"].get("remote", "")
    if remote_ctx and ctx == remote_ctx:
        return "remote"
    return f"custom ({ctx})"


def context_for(target: str) -> Optional[str]:
    """Return the kubectl context name for a target name."""
    cfg = load()
    return cfg["targets"].get(target)


def sentinel_image() -> str:
    cfg = load()
    return cfg.get("images", {}).get("sentinel", "klight-sentinel:latest")
