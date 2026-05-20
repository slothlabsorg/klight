"""
klight sync — download and apply klight-team.yaml.
Configures cluster targets, stores team config locally.

Usage:
  klight sync https://raw.githubusercontent.com/org/infra/main/klight-team.yaml
  klight sync   # re-sync from last known URL
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Optional
import yaml
import typer
from rich.console import Console

app = typer.Typer(help="Sync team configuration from klight-team.yaml URL.")
console = Console()

_TEAMS_DIR = Path.home() / ".klight" / "teams"
_SYNC_META = Path.home() / ".klight" / "sync.json"


def _teams_dir() -> Path:
    _TEAMS_DIR.mkdir(parents=True, exist_ok=True)
    return _TEAMS_DIR


def _load_sync_meta() -> dict:
    if _SYNC_META.exists():
        try:
            return json.loads(_SYNC_META.read_text())
        except Exception:
            pass
    return {}


def _save_sync_meta(meta: dict) -> None:
    _SYNC_META.parent.mkdir(parents=True, exist_ok=True)
    _SYNC_META.write_text(json.dumps(meta, indent=2))


def _download(url: str) -> str | None:
    """Download content from URL. Returns text or None."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        console.print(f"[red]Download failed:[/red] {e}")
        return None


def _apply_team_config(team_data: dict) -> None:
    """Apply targets from klight-team.yaml to kubectl config."""
    targets = team_data.get("targets", {})
    local_ctx = targets.get("local", "klight-demo")
    remote_url = team_data.get("remote", {}).get("api_url", "")

    # If remote context not yet configured but URL known, note it
    if remote_url:
        console.print(f"  [dim]Remote cluster: {remote_url}[/dim]")
        console.print(f"  [dim]To connect: klight connect --url {remote_url} --token <token>[/dim]")


def _fetch_service_klight_yaml(team_name: str, svc: dict) -> None:
    """Download a service's klight.yaml from its repo and cache it locally."""
    repo_url = svc.get("repo", "")
    svc_name = svc.get("name", "")
    if not repo_url or not svc_name:
        return

    raw_url = None
    if "github.com" in repo_url:
        parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/klight.yaml"
    elif "gitlab.com" in repo_url:
        parts = repo_url.rstrip("/").split("gitlab.com/")[-1]
        raw_url = f"https://gitlab.com/{parts}/-/raw/main/klight.yaml"

    if not raw_url:
        return

    content = _download(raw_url)
    if content:
        svc_dir = _teams_dir() / team_name / "services"
        svc_dir.mkdir(parents=True, exist_ok=True)
        (svc_dir / f"{svc_name}.yaml").write_text(content)


def get_service_klight_config(service_name: str):
    """Load cached klight.yaml for a service from the active team. Returns KlightConfig or None."""
    meta = _load_sync_meta()
    team_name = meta.get("active_team")
    if not team_name:
        return None
    svc_file = _teams_dir() / team_name / "services" / f"{service_name}.yaml"
    if not svc_file.exists():
        return None
    try:
        from klight.schema import KlightConfig
        return KlightConfig.from_file(svc_file)
    except Exception:
        return None


def get_team_service_image(service_name: str) -> str | None:
    """
    Look up a service's CI image from the last synced klight-team.yaml.
    Used by klight restore to find the original image.
    """
    meta = _load_sync_meta()
    team_name = meta.get("active_team")
    if not team_name:
        return None
    team_file = _teams_dir() / f"{team_name}.yaml"
    if not team_file.exists():
        return None
    data = yaml.safe_load(team_file.read_text()) or {}
    for svc in data.get("services", []):
        if svc.get("name") == service_name:
            return svc.get("image")
    return None


def get_active_team() -> dict | None:
    """Return the active team config dict, or None."""
    meta = _load_sync_meta()
    team_name = meta.get("active_team")
    if not team_name:
        return None
    team_file = _teams_dir() / f"{team_name}.yaml"
    if not team_file.exists():
        return None
    return yaml.safe_load(team_file.read_text())


def check_and_auto_sync() -> bool:
    """
    Called on `klight up` — checks if team config changed since yesterday.
    Returns True if synced, False if not needed or failed.
    """
    meta = _load_sync_meta()
    url = meta.get("url")
    if not url:
        return False

    last_sync = meta.get("last_sync", 0)
    hours_since = (time.time() - last_sync) / 3600
    if hours_since < 20:  # synced within 20 hours
        return False

    console.print("[dim]Checking for team config updates...[/dim]")
    content = _download(url)
    if not content:
        return False

    # Compare with cached
    team_name = meta.get("active_team", "team")
    team_file = _teams_dir() / f"{team_name}.yaml"
    cached = team_file.read_text() if team_file.exists() else ""
    if content == cached:
        meta["last_sync"] = time.time()
        _save_sync_meta(meta)
        return False

    # Changed — apply update
    team_file.write_text(content)
    data = yaml.safe_load(content) or {}
    meta["last_sync"] = time.time()
    _save_sync_meta(meta)

    svc_count = len(data.get("services", []))
    console.print(f"[green]Team config updated[/green] — {svc_count} services")
    return True


@app.command()
def cmd(
    url: str = typer.Argument("", help="URL to klight-team.yaml (or re-sync if omitted)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-sync even if up to date"),
) -> None:
    """
    Download and apply klight-team.yaml from a URL.
    Configures cluster targets and stores team config locally.

    Example:
      klight sync https://raw.githubusercontent.com/myorg/infra/main/klight-team.yaml
      klight sync   # re-sync from last URL
    """
    meta = _load_sync_meta()

    # Resolve URL
    target_url = url or meta.get("url", "")
    if not target_url:
        console.print("[red]No URL provided and no previous sync found.[/red]")
        console.print("Usage: klight sync https://raw.githubusercontent.com/.../klight-team.yaml")
        raise typer.Exit(1)

    console.print(f"[bold]Syncing[/bold] from: [dim]{target_url}[/dim]")
    content = _download(target_url)
    if not content:
        # Fall back to cached if available
        team_name = meta.get("active_team")
        if team_name and (_teams_dir() / f"{team_name}.yaml").exists():
            console.print("[yellow]Using cached config (offline)[/yellow]")
            return
        raise typer.Exit(1)

    data = yaml.safe_load(content) or {}
    team_name = data.get("team", "team")

    # Save
    team_file = _teams_dir() / f"{team_name}.yaml"
    team_file.write_text(content)
    meta.update({
        "url": target_url,
        "active_team": team_name,
        "last_sync": time.time(),
    })
    _save_sync_meta(meta)

    # Apply targets
    _apply_team_config(data)

    # Download each service's klight.yaml for offline use
    services = data.get("services", [])
    fetched = 0
    for svc in services:
        try:
            _fetch_service_klight_yaml(team_name, svc)
            fetched += 1
        except Exception:
            pass
    if fetched:
        console.print(f"  [dim]Cached {fetched} service configs[/dim]")

    # Summary
    svc_count = len(services)
    profiles = list(data.get("profiles", {}).keys())
    local_ctx = data.get("targets", {}).get("local", "klight-demo")

    console.print(f"\n[bold green]Team '{team_name}' configured[/bold green]")
    console.print(f"  Services:  {svc_count}")
    console.print(f"  Profiles:  {', '.join(profiles) or 'none'}")
    console.print(f"  Local target: {local_ctx}")
    console.print(f"\n  klight use local")
    if profiles:
        console.print(f"  klight up {profiles[0]} --env alice")
