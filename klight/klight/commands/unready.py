import typer
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Show services that are not ready, with a fix hint.")
console = Console()


def run(env_name: str) -> bool:
    """Returns True if all services are ready, False if any are broken."""
    ns = f"env-{env_name}"
    data = k.run_json(["get", "pods", "-n", ns])
    if not data:
        console.print(f"[red]Could not list pods in namespace {ns}[/red]")
        return False

    broken = []
    for pod in data.get("items", []):
        meta = pod["metadata"]
        status = pod["status"]
        labels = meta.get("labels", {})
        service_name = labels.get("app", meta["name"])
        phase = status.get("phase", "Unknown")
        container_statuses = status.get("containerStatuses", [])

        if phase in ("Succeeded", "Completed"):
            continue
        issue = None

        # Check init container problems
        for init in status.get("initContainerStatuses", []):
            if not init.get("ready"):
                state = init.get("state", {})
                if "waiting" in state:
                    reason = state["waiting"].get("reason", "Waiting")
                    issue = f"Init:{reason}"
                    break

        # Check main containers
        if issue is None:
            for cs in container_statuses:
                if not cs.get("ready"):
                    state = cs.get("state", {})
                    restarts = cs.get("restartCount", 0)
                    if "waiting" in state:
                        reason = state["waiting"].get("reason", "NotReady")
                        issue = reason
                        if restarts > 0:
                            issue = f"{reason} ({restarts}x restarts)"
                    elif "terminated" in state:
                        reason = state["terminated"].get("reason", "Terminated")
                        issue = reason
                    elif phase != "Running":
                        issue = phase
                    break

        if issue:
            broken.append((service_name, issue))

    if not broken:
        console.print("[green] All services ready.[/green]")
        return True

    for service_name, issue in broken:
        console.print(f"[red] {service_name:<25}[/red] [yellow]{issue}[/yellow]")
        console.print(f"   [dim]→ Check: klight logs {service_name} --env {env_name}[/dim]")

    return False


@app.command()
def cmd(
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Show services that are not ready. Prints fix hint for each."""
    all_ready = run(env_name)
    if not all_ready:
        raise typer.Exit(1)
