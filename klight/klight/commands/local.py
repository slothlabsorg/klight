import math
import subprocess
import typer
from pathlib import Path
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Local minikube management: setup, build-load, status.")
console = Console()

MINIKUBE_PROFILE = "klight-demo"

# Static memory estimates (MB) for sizing calculations
_INFRA_MEMORY_MB: dict[str, int] = {
    "postgres": 512,
    "kafka": 1024,
    "redis": 256,
    "mongodb": 512,
    "mysql": 512,
    "rabbitmq": 256,
    "elasticsearch": 1024,
    "localstack": 512,
}
_SERVICE_MEMORY_MB = 256
_K8S_OVERHEAD_MB = 512


def _estimate_profile_mb(profile_name: str) -> dict:
    """Estimate memory needs for a profile. Returns sizing dict or {error: str}."""
    try:
        from klight.commands.sync import get_active_team, get_service_klight_config
        team = get_active_team()
        if not team:
            return {"error": "No team synced. Run: klight sync <url>"}
        profiles = team.get("profiles", {})
        if profile_name not in profiles:
            return {"error": f"Profile '{profile_name}' not found in synced team"}
        service_names = profiles[profile_name]
        if isinstance(service_names, str):
            service_names = [service_names]
        infra_set: set[str] = set()
        for svc_name in service_names:
            cfg_obj = get_service_klight_config(svc_name)
            if cfg_obj:
                for need in (cfg_obj.needs or []):
                    need_name = need if isinstance(need, str) else need.name
                    infra_set.add(need_name)
        services_mb = len(service_names) * _SERVICE_MEMORY_MB
        infra_mb = sum(_INFRA_MEMORY_MB.get(n, 512) for n in infra_set)
        estimated_mb = services_mb + infra_mb + _K8S_OVERHEAD_MB
        recommended_mb = max(2048, math.ceil(estimated_mb / 512) * 512)
        return {
            "profile": profile_name,
            "service_count": len(service_names),
            "infra": sorted(infra_set),
            "services_mb": services_mb,
            "infra_mb": infra_mb,
            "estimated_mb": estimated_mb,
            "recommended_mb": recommended_mb,
        }
    except Exception as e:
        return {"error": str(e)}


def _minikube(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["minikube"] + args, capture_output=capture, text=True)


@app.command()
def setup(
    cpus: int = typer.Option(2, "--cpus", help="Number of CPUs for minikube"),
    memory: int = typer.Option(3072, "--memory", help="Memory in MB"),
    profile: str = typer.Option(MINIKUBE_PROFILE, "--profile", help="minikube profile name"),
) -> None:
    """Start a local minikube cluster for klight development."""
    console.print(f"[bold]Starting minikube profile:[/bold] {profile}")
    console.print(f"  CPUs: {cpus}, Memory: {memory}MB, Driver: docker")

    result = _minikube([
        "start",
        f"--profile={profile}",
        "--driver=docker",
        f"--cpus={cpus}",
        f"--memory={memory}",
        "--kubernetes-version=stable",
    ])

    if result.returncode != 0:
        console.print("[red]minikube start failed. Is Docker running?[/red]")
        raise typer.Exit(1)

    # Enable ingress addon
    console.print("  Enabling ingress addon...")
    _minikube(["addons", "enable", "ingress", f"--profile={profile}"])

    # Set kubectl context
    result = subprocess.run(
        ["kubectl", "config", "use-context", profile],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"[yellow]Warning: could not set kubectl context to {profile}[/yellow]")

    console.print(f"\n[bold green]minikube {profile} is ready.[/bold green]")
    console.print(f"  kubectl context: {profile}")
    console.print(f"  Next: klight local build-load <service> --path ./<service-dir>")


@app.command()
def build_load(
    service: str = typer.Argument(..., help="Service name (used as image name)"),
    path: Path = typer.Option(..., "--path", help="Path to the service directory with Dockerfile"),
    tag: str = typer.Option("local", "--tag", help="Image tag (default: local)"),
    profile: str = typer.Option(MINIKUBE_PROFILE, "--profile", help="minikube profile"),
) -> None:
    """Build a Docker image and load it into minikube."""
    image = f"{service}:{tag}"

    if not path.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise typer.Exit(1)
    if not (path / "Dockerfile").exists():
        console.print(f"[red]No Dockerfile found in:[/red] {path}")
        raise typer.Exit(1)

    console.print(f"[bold]Building[/bold] {image} from {path}...")
    result = subprocess.run(
        ["docker", "build", "-t", image, str(path)],
        capture_output=False,
    )
    if result.returncode != 0:
        console.print(f"[red]docker build failed[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Loading[/bold] {image} into minikube ({profile})...")
    result = _minikube(["image", "load", image, f"--profile={profile}"])
    if result.returncode != 0:
        console.print(f"[red]minikube image load failed[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] {image} is ready in minikube")


@app.command()
def resize(
    memory: int = typer.Option(..., "--memory", help="Memory in MB (e.g. 4096)"),
    cpus: int = typer.Option(2, "--cpus", help="Number of CPUs"),
    profile: str = typer.Option(MINIKUBE_PROFILE, "--profile", help="minikube profile"),
) -> None:
    """Resize the minikube cluster. Stops then restarts with new resources."""
    console.print(f"[bold]Resizing {profile}:[/bold] {cpus} CPUs, {memory} MB")
    console.print("  Stopping cluster...")
    _minikube(["stop", f"--profile={profile}"])
    console.print("  Starting with new resources...")
    r = _minikube([
        "start",
        f"--profile={profile}",
        "--driver=docker",
        f"--cpus={cpus}",
        f"--memory={memory}",
        "--kubernetes-version=v1.30.0",
    ])
    if r.returncode != 0:
        console.print("[red]minikube start failed[/red]")
        raise typer.Exit(1)
    kubeconfig_path = "/tmp/klight-demo-kubeconfig.yaml"
    r2 = subprocess.run(
        ["minikube", "-p", profile, "kubectl", "--", "config", "view", "--raw"],
        capture_output=True, text=True,
    )
    if r2.returncode == 0 and r2.stdout:
        Path(kubeconfig_path).write_text(r2.stdout)
        console.print(f"  [dim]Kubeconfig updated: {kubeconfig_path}[/dim]")
    console.print(f"\n[bold green]{profile} resized: {cpus} CPUs, {memory} MB[/bold green]")
    console.print(f"  KUBECONFIG={kubeconfig_path} klight ps --env <name>")


@app.command()
def status(
    profile: str = typer.Option(MINIKUBE_PROFILE, "--profile", help="minikube profile"),
) -> None:
    """Show minikube status and loaded images."""
    console.print(f"[bold]minikube status ({profile}):[/bold]")
    _minikube(["status", f"--profile={profile}"])

    console.print(f"\n[bold]Loaded images:[/bold]")
    result = _minikube(["image", "ls", f"--profile={profile}"], capture=True)
    if result.returncode == 0:
        # Filter to show only non-system images
        lines = [l for l in result.stdout.splitlines() if ":local" in l or "store-" in l or "inventory-" in l]
        if lines:
            for line in lines:
                console.print(f"  {line}")
        else:
            console.print("  [dim]No klight images found. Run: klight local build-load <service> --path <dir>[/dim]")
