"""
Profile management — groups of services started together.
Supports includes: to compose profiles (e.g. vertical2 includes core).
"""

import subprocess
import yaml
import typer
from pathlib import Path
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Service profile management.")
console = Console()


def _load_team_profile(name: str) -> dict | None:
    """Load a profile from the synced klight-team.yaml. Returns dict or None."""
    try:
        from klight.commands.sync import get_active_team
        team = get_active_team()
        if not team:
            return None
        profiles = team.get("profiles", {})
        if name not in profiles:
            return None
        service_names = profiles[name]
        if isinstance(service_names, str):
            service_names = [service_names]
        # Resolve infra from each service's cached klight.yaml
        from klight.commands.sync import get_service_klight_config
        infra_set: set[str] = set()
        svc_list = []
        for svc_name in service_names:
            cfg = get_service_klight_config(svc_name)
            if cfg:
                for need in (cfg.needs or []):
                    need_name = need if isinstance(need, str) else need.name
                    infra_set.add(need_name)
            svc_list.append({"name": svc_name})
        return {
            "name": name,
            "infrastructure": sorted(infra_set),
            "migrations": [],
            "services": svc_list,
            "healthChecks": [],
            "_from_team": True,
        }
    except Exception:
        return None


def _load_profile(name: str, manifests_dir=None) -> dict:
    from klight import kubectl as kctl
    mdir = Path(manifests_dir) if manifests_dir else kctl.get_manifests_dir()
    # Check standard location
    for candidate in [
        mdir / "profiles" / f"{name}.yaml",
        Path("profiles") / f"{name}.yaml",
        Path(f"{name}.yaml"),
    ]:
        if candidate.exists():
            with open(candidate) as f:
                return yaml.safe_load(f) or {}
    # Fall back to synced team config
    team_profile = _load_team_profile(name)
    if team_profile is not None:
        return team_profile
    raise FileNotFoundError(f"Profile '{name}' not found. Looked in: {mdir}/profiles/")


def _resolve_profile(name: str, manifests_dir=None) -> dict:
    """Load a profile and recursively merge includes:."""
    from klight import kubectl as kctl
    mdir = Path(manifests_dir) if manifests_dir else kctl.get_manifests_dir()
    profile = _load_profile(name, mdir)

    merged = {
        "name": profile.get("name", name),
        "includes": profile.get("includes", []),
        "infrastructure": list(profile.get("infrastructure", [])),
        "migrations": list(profile.get("migrations", [])),
        "services": list(profile.get("services", [])),
        "healthChecks": list(profile.get("healthChecks", [])),
        "_from_team": profile.get("_from_team", False),
    }

    for inc in profile.get("includes", []):
        inc_name = inc.replace(".yaml", "")
        try:
            included = _resolve_profile(inc_name, mdir)
            # Prepend included items (core starts first, before this profile's services)
            for key in ("infrastructure", "migrations", "services", "healthChecks"):
                existing_names = set()
                for item in merged[key]:
                    existing_names.add(item.get("name", item) if isinstance(item, dict) else item)
                prepend = []
                for item in included.get(key, []):
                    item_name = item.get("name", item) if isinstance(item, dict) else item
                    if item_name not in existing_names:
                        prepend.append(item)
                        existing_names.add(item_name)
                merged[key] = prepend + merged[key]
        except FileNotFoundError as e:
            console.print(f"[yellow]Warning: {e}[/yellow]")

    return merged


def _ensure_global_config(ns: str) -> None:
    """Create klight-global-config and klight-global-secrets if they don't exist."""
    cm = k.run(["get", "configmap", "klight-global-config", "-n", ns])
    if cm.returncode != 0:
        k.run(["create", "configmap", "klight-global-config",
               "--from-literal=ENVIRONMENT=dev",
               "--from-literal=LOG_LEVEL=INFO",
               "-n", ns])
    sec = k.run(["get", "secret", "klight-global-secrets", "-n", ns])
    if sec.returncode != 0:
        k.run(["create", "secret", "generic", "klight-global-secrets",
               "--from-literal=POSTGRES_PASSWORD=klight",
               "--from-literal=SECRET_KEY=dev-secret-key",
               "-n", ns])


def _apply_from_team(profile: dict, ns: str) -> None:
    """Deploy services using cached klight.yaml + team images. No local infra repo needed."""
    from klight.commands.sync import get_service_klight_config, get_active_team
    from klight import manifest_gen
    from klight.catalog import load as load_catalog, get as catalog_get

    team = get_active_team() or {}
    team_images = {svc["name"]: svc.get("image", "") for svc in team.get("services", [])}

    # Try to find local manifests dir for infra kustomize overlays
    try:
        from klight import kubectl as kctl
        mdir = kctl.get_manifests_dir()
    except Exception:
        mdir = None

    # Deploy infra
    for infra_name in profile.get("infrastructure", []):
        console.print(f"  Deploying infra/{infra_name}...")
        deployed = False
        if mdir:
            for overlay in ["base", "overlays/dev"]:
                infra_path = mdir / "infrastructure" / infra_name / overlay
                if infra_path.exists():
                    k.apply_kustomize(infra_path, ns)
                    deployed = True
                    break
        if not deployed:
            entry = catalog_get(infra_name) or {}
            img = entry.get("image", f"{infra_name}:latest")
            port_num = entry.get("port", 5432)
            for m in manifest_gen.infra_manifest(infra_name, img, port_num, ns):
                manifest_gen.kubectl_apply_manifest(m, ns)
        console.print(f"  [green]✓[/green] infra/{infra_name}")

    # Wait for infra to be ready
    for infra_name in profile.get("infrastructure", []):
        k.run(["wait", "--for=condition=ready", f"pod/{infra_name}-0",
               "-n", ns, "--timeout=120s"])

    # Deploy services using cached klight.yaml + team image
    for svc_entry in profile.get("services", []):
        svc_name = svc_entry.get("name") if isinstance(svc_entry, dict) else svc_entry
        cfg = get_service_klight_config(svc_name)
        if not cfg:
            console.print(f"  [yellow]⚠[/yellow] No klight.yaml cached for {svc_name} — run: klight sync")
            continue
        team_image = team_images.get(svc_name, "")
        if team_image:
            cfg.image = team_image
        console.print(f"  Deploying {svc_name} ({cfg.image or 'no image'})...")
        for m in manifest_gen.all_manifests(cfg):
            manifest_gen.kubectl_apply_manifest(m, ns)
        console.print(f"  [green]✓[/green] {svc_name}")


def _apply_profile(profile: dict, ns: str, manifests_dir=None) -> None:
    # Team-sourced profile: use manifest_gen instead of kustomize
    if profile.get("_from_team"):
        _apply_from_team(profile, ns)
        return

    from klight import kubectl as kctl
    mdir = Path(manifests_dir) if manifests_dir else kctl.get_manifests_dir()

    for infra_name in profile.get("infrastructure", []):
        infra_path = mdir / "infrastructure" / infra_name / "base"
        if infra_path.exists():
            k.apply_kustomize(infra_path, ns)
            console.print(f"  [green]✓[/green] infra/{infra_name}")

    for infra_name in profile.get("infrastructure", []):
        k.run(["wait", "--for=condition=ready", f"pod/{infra_name}-0",
               "-n", ns, "--timeout=120s"])

    for mig in profile.get("migrations", []):
        job_name = mig.get("job") if isinstance(mig, dict) else mig
        k.run(["delete", "job", job_name, "-n", ns, "--ignore-not-found"])
        job_path = mdir / "jobs" / job_name / "base"
        if job_path.exists():
            k.apply_kustomize(job_path, ns)
            k.run(["wait", "--for=condition=complete", f"job/{job_name}",
                   "-n", ns, "--timeout=120s"])
            console.print(f"  [green]✓[/green] migration/{job_name}")

    for svc in profile.get("services", []):
        svc_name = svc.get("name") if isinstance(svc, dict) else svc
        for overlay in ["overlays/dev", "base"]:
            svc_path = mdir / "services" / svc_name / overlay
            if svc_path.exists():
                k.apply_kustomize(svc_path, ns)
                console.print(f"  [green]✓[/green] {svc_name}")
                break


@app.command()
def up(
    name: str = typer.Argument(..., help="Profile name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    timeout: int = typer.Option(300, "--timeout"),
) -> None:
    """Bring up all services in a profile. Supports includes: for composed profiles."""
    from klight.commands._context import assert_safe_context
    assert_safe_context()
    ns = f"env-{env_name}"
    from klight import kubectl as kctl
    console.print(f"\n[bold]Profile:[/bold] {name} → {env_name}\n")

    # Ensure namespace exists with klight.env label (for UI discovery)
    if not kctl.namespace_exists(ns):
        k.run(["create", "namespace", ns])
        console.print(f"  [dim]Created namespace {ns}[/dim]")
    k.run(["label", "namespace", ns, f"klight.env={env_name}", "--overwrite"])
    _ensure_global_config(ns)

    try:
        mdir = kctl.get_manifests_dir()
    except RuntimeError:
        mdir = None

    try:
        profile = _resolve_profile(name, mdir)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if profile.get("includes"):
        console.print(f"  [dim]Includes: {', '.join(profile['includes'])}[/dim]")

    _apply_profile(profile, ns, mdir)

    if mdir:
        startup = mdir / "jobs" / f"{name}-startup" / "base"
        if startup.exists():
            k.run(["delete", "job", f"{name}-startup", "-n", ns, "--ignore-not-found"])
            k.apply_kustomize(startup, ns)
            k.run(["wait", "--for=condition=complete", f"job/{name}-startup",
                   "-n", ns, f"--timeout={timeout}s"], capture=False)

    console.print(f"\n[bold green]Profile '{name}' ready in '{env_name}'[/bold green]")


@app.command()
def down(
    name: str = typer.Argument(...),
    env_name: str = typer.Option(..., "--env"),
) -> None:
    """Scale down all services in a profile."""
    from klight.commands._context import assert_safe_context
    assert_safe_context()
    ns = f"env-{env_name}"
    from klight import kubectl as kctl
    try:
        profile = _resolve_profile(name, kctl.get_manifests_dir())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    for svc in profile.get("services", []):
        svc_name = svc.get("name") if isinstance(svc, dict) else svc
        k.run(["scale", "deployment", svc_name, "--replicas=0", "-n", ns])
        console.print(f"[green]✓[/green] Scaled down {svc_name}")
    console.print(f"\n[yellow]Profile '{name}' scaled down in '{env_name}'[/yellow]")


@app.command(name="list")
def list_profiles() -> None:
    """List all defined profiles."""
    from klight import kubectl as kctl
    profiles_dir = kctl.get_manifests_dir() / "profiles"
    if not profiles_dir.exists():
        console.print("No profiles found.")
        return
    for p in sorted(profiles_dir.glob("*.yaml")):
        data = yaml.safe_load(p.read_text()) or {}
        desc = data.get("description", "")
        includes = data.get("includes", [])
        inc_str = f" ← includes {', '.join(includes)}" if includes else ""
        console.print(f"  [cyan]{p.stem}[/cyan] — {desc}{inc_str}")


@app.command()
def status(
    name: str = typer.Argument(...),
    env_name: str = typer.Option(..., "--env"),
) -> None:
    """Show health of each service in a profile."""
    ns = f"env-{env_name}"
    from klight import kubectl as kctl
    try:
        profile = _resolve_profile(name, kctl.get_manifests_dir())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"\n[bold]{name}[/bold] in {env_name}:\n")
    for svc in profile.get("services", []):
        svc_name = svc.get("name") if isinstance(svc, dict) else svc
        result = k.run(["get", "deployment", svc_name, "-n", ns,
                        "--no-headers", "-o", "custom-columns=READY:.status.readyReplicas"])
        ready = result.stdout.strip() if result.returncode == 0 else "?"
        marker = "[green]✓[/green]" if ready not in ("", "<none>", "?") else "[red]✗[/red]"
        console.print(f"  {marker} {svc_name}")
