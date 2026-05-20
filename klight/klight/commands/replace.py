"""
klight replace — swap a running service with a local build.
klight restore — revert to the CI image from klight-team.yaml or klight.yaml.

This is the core "dev working on one service" workflow:
  klight up vertical1 --env alice          # everything runs from CI images
  klight replace vertical1-api --with .    # only vertical1-api uses local build
  klight watch vertical1-api --env alice   # hotreload
  klight restore vertical1-api --env alice # back to CI image
"""

import json
import subprocess
import os
from pathlib import Path
import typer
from rich.console import Console
from klight import kubectl as k
from klight.schema import KlightConfig

app = typer.Typer(help="Swap a service with a local build (or restore to CI image).")
console = Console()

# Where we store "original image before replace" for each service
_STATE_DIR = Path.home() / ".klight" / "replaced"


def _current_image(service: str, namespace: str) -> str | None:
    """Get the current image running in a deployment."""
    result = k.run([
        "get", "deployment", service, "-n", namespace,
        "-o", "jsonpath={.spec.template.spec.containers[0].image}",
    ])
    return result.stdout.strip() if result.returncode == 0 else None


def _set_image(service: str, namespace: str, image: str) -> bool:
    """Update deployment image and wait for rollout."""
    result = k.run([
        "set", "image", f"deployment/{service}",
        f"{service}={image}", "-n", namespace,
    ])
    if result.returncode != 0:
        console.print(f"[red]Failed to set image:[/red] {result.stderr.strip()}")
        return False
    k.run(["rollout", "status", f"deployment/{service}", "-n", namespace,
           "--timeout=120s"], capture=False)
    return True


def _build_image(service: str, path: Path, cfg: KlightConfig | None) -> str | None:
    """Build Docker image. Returns the image tag or None on failure."""
    tag = f"{service}:local"

    if cfg and cfg.build and cfg.build.command:
        # Custom build command (Gradle Jib, SBT, etc.)
        cmd = cfg.build.command
        cwd = (path / cfg.build.context).resolve()
        console.print(f"  [dim]$ {cmd}[/dim]")
        result = subprocess.run(cmd, shell=True, cwd=str(cwd))
        if result.returncode != 0:
            return None
        return cfg.build.tag or tag

    # Standard Dockerfile build
    dockerfile = path / "Dockerfile"
    if not dockerfile.exists():
        console.print(f"[red]No Dockerfile found at {path}[/red]")
        console.print("Add a build: section to klight.yaml for custom builds.")
        return None

    console.print(f"  [dim]$ docker build -t {tag} {path}[/dim]")
    result = subprocess.run(["docker", "build", "-t", tag, str(path)])
    return tag if result.returncode == 0 else None


def _is_local_target() -> bool:
    """True if current kubectl context is minikube (local)."""
    result = subprocess.run(
        ["kubectl", "config", "current-context"], capture_output=True, text=True
    )
    ctx = result.stdout.strip()
    return ctx in ("klight-demo", "minikube") or "minikube" in ctx


def _load_to_minikube(image: str, profile: str = "klight-demo") -> bool:
    result = subprocess.run(
        ["minikube", "image", "load", image, f"--profile={profile}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _push_to_registry(image: str, registry: str | None) -> str | None:
    """
    Push local image to a registry.
    Returns the remote image tag, or None if push failed/no perms.
    """
    if not registry:
        return None
    remote_tag = f"{registry}/{image}"
    result = subprocess.run(
        ["docker", "tag", image, remote_tag], capture_output=True
    )
    if result.returncode != 0:
        return None
    result = subprocess.run(["docker", "push", remote_tag], capture_output=True)
    if result.returncode != 0:
        console.print(f"[yellow]Push failed — no registry permissions.[/yellow]")
        console.print(f"  Options:")
        console.print(f"  1. Ask DevOps for push access to {registry}")
        console.print(f"  2. `klight use local` to work on local minikube instead")
        return None
    return remote_tag


def _save_original(service: str, namespace: str, image: str) -> None:
    """Save the original image so restore can revert it."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = _STATE_DIR / f"{namespace}-{service}.json"
    state_file.write_text(json.dumps({"service": service, "namespace": namespace, "original_image": image}))


def _load_original(service: str, namespace: str) -> str | None:
    state_file = _STATE_DIR / f"{namespace}-{service}.json"
    if not state_file.exists():
        return None
    return json.loads(state_file.read_text()).get("original_image")


@app.command()
def replace(
    service: str = typer.Argument(..., help="Service name to replace"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    path: Path = typer.Option(Path("."), "--with", help="Path to service repo to build from"),
    minikube_profile: str = typer.Option("klight-demo", "--profile"),
) -> None:
    """
    Replace a running service with a local build.
    Other services keep running from their CI images.

    Example:
      klight up vertical1 --env alice
      git clone vertical1-api && cd vertical1-api
      klight replace vertical1-api --with . --env alice
    """
    ns = f"env-{env_name}"
    repo_path = path.resolve()

    # Load klight.yaml if present
    cfg = None
    klf = repo_path / "klight.yaml"
    if klf.exists():
        cfg = KlightConfig.from_file(klf)

    # Save original image for restore
    original = _current_image(service, ns)
    if original:
        _save_original(service, ns, original)
        console.print(f"  Saved original image: [dim]{original}[/dim]")

    # Build
    console.print(f"\n[bold]Building[/bold] {service} from {repo_path.name}/...")
    image = _build_image(service, repo_path, cfg)
    if not image:
        console.print(f"[red]Build failed.[/red]")
        raise typer.Exit(1)
    console.print(f"  [green]✓[/green] Built: {image}")

    # Load or push
    is_local = _is_local_target()
    if is_local:
        console.print(f"  Loading into minikube ({minikube_profile})...")
        if not _load_to_minikube(image, minikube_profile):
            console.print("[red]minikube image load failed[/red]")
            raise typer.Exit(1)
        deploy_image = image
    else:
        # Remote: try to push to registry
        from klight.config import load as load_cfg
        registry = load_cfg().get("images", {}).get("registry", "")
        if registry:
            console.print(f"  Pushing to {registry}...")
            deploy_image = _push_to_registry(image, registry)
            if not deploy_image:
                console.print("[red]Push failed. Use 'klight use local' to work on minikube instead.[/red]")
                raise typer.Exit(1)
        else:
            console.print("[yellow]Remote cluster: no registry configured in klight.toml.[/yellow]")
            console.print("  Add [images] registry=ghcr.io/myorg to klight.toml")
            console.print("  Or: klight use local")
            raise typer.Exit(1)

    # Update deployment
    console.print(f"  Updating deployment/{service}...")
    if not _set_image(service, ns, deploy_image):
        raise typer.Exit(1)

    console.print(f"\n[bold green]✓ {service}[/bold green] → local build in '{env_name}'")
    console.print(f"  klight watch {service} --env {env_name} --path {repo_path}")
    console.print(f"  klight restore {service} --env {env_name}  (to revert)")


@app.command()
def restore(
    service: str = typer.Argument(..., help="Service name to restore"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    image: str = typer.Option("", "--image", help="Specific image to restore to (optional)"),
) -> None:
    """
    Restore a service to its CI image (undo klight replace).

    Uses the image saved before the last replace, or the image from klight-team.yaml.
    """
    ns = f"env-{env_name}"

    # Determine restore image
    target_image = image

    if not target_image:
        # Try saved original
        target_image = _load_original(service, ns)

    if not target_image:
        # Try klight-team.yaml
        from klight.commands.sync import get_team_service_image
        target_image = get_team_service_image(service)

    if not target_image:
        # Try local klight.yaml
        for path in [Path("."), Path(f"./{service}")]:
            klf = path / "klight.yaml"
            if klf.exists():
                cfg = KlightConfig.from_file(klf)
                target_image = cfg.image
                break

    if not target_image:
        console.print(f"[red]Cannot determine original image for {service}.[/red]")
        console.print(f"  Specify with: klight restore {service} --env {env_name} --image ghcr.io/org/svc:main")
        raise typer.Exit(1)

    console.print(f"[bold]Restoring[/bold] {service} → [dim]{target_image}[/dim]")
    if not _set_image(service, ns, target_image):
        raise typer.Exit(1)

    # Clean up saved state
    state_file = _STATE_DIR / f"{ns}-{service}.json"
    state_file.unlink(missing_ok=True)

    console.print(f"[green]✓[/green] {service} restored to CI image in '{env_name}'")
