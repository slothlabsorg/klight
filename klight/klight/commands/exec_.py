import subprocess
import typer
from typing import List
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Exec into a service pod by service name.")
console = Console()


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def cmd(
    service: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    ctx: typer.Context = typer.Option(None),
) -> None:
    """Exec into the first running pod of a service."""
    ns = f"env-{env_name}"
    extra_args = ctx.args if ctx else []

    # Find the first running pod with label app=<service>
    data = k.run_json([
        "get", "pods", "-n", ns,
        "-l", f"app={service}",
        "--field-selector", "status.phase=Running",
    ])

    if not data or not data.get("items"):
        console.print(f"[red]No running pod found for service '{service}' in env '{env_name}'[/red]")
        console.print(f"  Check: klight ps --env {env_name}")
        raise typer.Exit(1)

    pod_name = data["items"][0]["metadata"]["name"]

    if not extra_args:
        extra_args = ["/bin/sh"]

    console.print(f"[dim]Execing into {pod_name}[/dim]")
    subprocess.run(["kubectl", "exec", "-it", pod_name, "-n", ns, "--"] + extra_args)
