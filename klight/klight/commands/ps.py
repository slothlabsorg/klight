import typer
from rich.console import Console
from rich.table import Table
from rich import box
from klight import kubectl as k

app = typer.Typer(help="Pretty service status table (no pod hashes, no K8s jargon).")
console = Console()


def run(env_name: str) -> None:
    ns = f"env-{env_name}"
    data = k.run_json(["get", "pods", "-n", ns])
    if not data:
        console.print(f"[red]Could not list pods in namespace {ns}[/red]")
        raise typer.Exit(1)

    items = data.get("items", [])
    if not items:
        console.print(f"No pods found in environment '{env_name}'.")
        return

    table = Table(
        title=f"Environment: [cyan]{env_name}[/cyan] (namespace: {ns})",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
    )
    table.add_column("SERVICE", style="cyan", min_width=20)
    table.add_column("READY", min_width=8)
    table.add_column("STATUS", min_width=16)
    table.add_column("RESTARTS", justify="right", min_width=8)
    table.add_column("AGE", min_width=8)

    for pod in sorted(items, key=lambda p: p["metadata"]["name"]):
        meta = pod["metadata"]
        status = pod["status"]

        # Service name: strip pod hash suffix (last 2 segments for Deployment pods)
        name = meta["name"]
        labels = meta.get("labels", {})
        service_name = labels.get("app", name)  # use app label if available

        # Ready: X/Y containers
        container_statuses = status.get("containerStatuses", [])
        ready_count = sum(1 for c in container_statuses if c.get("ready"))
        total_count = len(container_statuses) or 1
        ready_str = f"{ready_count}/{total_count}"

        # Phase / condition
        phase = status.get("phase", "Unknown")

        # Check for init container issues
        init_statuses = status.get("initContainerStatuses", [])
        for init in init_statuses:
            if not init.get("ready") and init.get("state", {}).get("waiting"):
                reason = init["state"]["waiting"].get("reason", "")
                if reason:
                    phase = f"Init:{reason}"
                    break

        # Check for container-level issues
        for cs in container_statuses:
            state = cs.get("state", {})
            if "waiting" in state:
                reason = state["waiting"].get("reason", "")
                if reason:
                    phase = reason
                    break

        # Restarts
        restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)

        # Age
        creation = meta.get("creationTimestamp", "")
        age = _format_age(creation)

        # Color by status
        if phase == "Running" and ready_count == total_count:
            status_str = f"[green]{phase}[/green]"
            ready_str = f"[green]{ready_str}[/green]"
        elif phase in ("Pending", "ContainerCreating") or phase.startswith("Init:"):
            status_str = f"[yellow]{phase}[/yellow]"
            ready_str = f"[yellow]{ready_str}[/yellow]"
        else:
            status_str = f"[red]{phase}[/red]"
            ready_str = f"[red]{ready_str}[/red]"

        restart_str = f"[red]{restarts}[/red]" if restarts > 3 else str(restarts)

        table.add_row(service_name, ready_str, status_str, restart_str, age)

    console.print(table)


def _format_age(timestamp: str) -> str:
    if not timestamp:
        return "?"
    from datetime import datetime, timezone
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - created
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        elif seconds < 86400:
            return f"{seconds // 3600}h"
        else:
            return f"{seconds // 86400}d"
    except Exception:
        return "?"


@app.command()
def cmd(
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Show all services in an environment. No pod hashes, no K8s jargon."""
    run(env_name)
