import subprocess
import typer
from rich.console import Console
from pathlib import Path
from klight import kubectl as k

app = typer.Typer(help="Service deployment and operations.")
console = Console()


@app.command()
def deploy(
    name: str = typer.Argument(..., help="Service name (must match manifests/services/<name>/)"),
    env_name: str = typer.Option(..., "--env", help="Target environment"),
    image: str = typer.Option(None, "--image", help="Docker image to deploy (e.g. registry/svc:sha)"),
    overlay: str = typer.Option(None, "--overlay", help="Path to kustomize overlay (default: overlays/dev)"),
) -> None:
    """Deploy a service to an environment."""
    ns = f"env-{env_name}"
    manifests = k.get_manifests_dir()

    overlay_path = Path(overlay) if overlay else manifests / "services" / name / "overlays" / "dev"
    if not overlay_path.exists():
        console.print(f"[red]Overlay not found:[/red] {overlay_path}")
        console.print(f"Run: cp -r manifests/services/_template manifests/services/{name}")
        raise typer.Exit(1)

    if image:
        result = subprocess.run(
            ["kustomize", "edit", "set", "image", f"{name}={image}"],
            cwd=str(overlay_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[yellow]Warning: could not set image via kustomize:[/yellow] {result.stderr.strip()}")
            console.print("Set the image directly in the deployment.yaml instead.")

    k.apply_kustomize(overlay_path, ns)
    console.print(f"[green]✓[/green] Deployed {name} to {env_name}")
    if image:
        console.print(f"  Image: {image}")

    result = k.run(["rollout", "status", f"deployment/{name}", "-n", ns, "--timeout=120s"], capture=False)
    if result.returncode != 0:
        console.print(f"[yellow]Warning: rollout did not complete within 120s.[/yellow]")
        console.print(f"Check: kubectl -n {ns} get pods -l app={name}")


@app.command()
def logs(
    name: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream logs"),
    tail: int = typer.Option(100, "--tail", help="Number of lines to show"),
    since: str = typer.Option(None, "--since", help="Time window (e.g. 30m, 1h)"),
    container: str = typer.Option(None, "--container", "-c", help="Container name"),
) -> None:
    """Stream or fetch logs from a service."""
    ns = f"env-{env_name}"
    args = ["logs", f"deployment/{name}", "-n", ns, f"--tail={tail}"]
    if follow:
        args.append("-f")
    if since:
        args.append(f"--since={since}")
    if container:
        args.extend(["-c", container])
    k.run(args, capture=False)


@app.command()
def restart(
    name: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment"),
) -> None:
    """Rolling restart a service."""
    ns = f"env-{env_name}"
    result = k.run(["rollout", "restart", f"deployment/{name}", "-n", ns])
    if result.returncode != 0:
        console.print(f"[red]Error:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Restarted {name} in {env_name}")


@app.command()
def scale(
    name: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment"),
    replicas: int = typer.Option(..., "--replicas", help="Number of replicas"),
) -> None:
    """Scale a service to N replicas."""
    ns = f"env-{env_name}"
    result = k.run(["scale", "deployment", name, f"--replicas={replicas}", "-n", ns])
    if result.returncode != 0:
        console.print(f"[red]Error:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] {name} scaled to {replicas} replicas in {env_name}")
