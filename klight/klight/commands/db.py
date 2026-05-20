import subprocess
import typer
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Database migration and access.")
console = Console()

_SHELLS = {
    "postgres": ["psql", "-U", "klight"],
    "redis": ["redis-cli"],
    "mysql": ["mysql", "-u", "klight", "-p"],
    "mongodb": ["mongosh"],
}


@app.command()
def migrate(
    service: str = typer.Argument(..., help="Service name (looks for jobs/{service}-dbmigrate/)"),
    env_name: str = typer.Option(..., "--env", help="Target environment"),
    job_name: str = typer.Option(None, "--job", help="Override job name"),
    timeout: int = typer.Option(120, "--timeout", help="Seconds to wait for job completion"),
) -> None:
    """Run database migrations for a service."""
    ns = f"env-{env_name}"
    job = job_name or f"{service}-dbmigrate"
    manifests = k.get_manifests_dir()
    job_path = manifests / "jobs" / job / "base"

    if not job_path.exists():
        console.print(f"[red]Migration job not found:[/red] {job_path}")
        console.print(f"Run: cp -r manifests/jobs/_template manifests/jobs/{job}")
        raise typer.Exit(1)

    # Delete existing job if present (to allow re-running)
    k.run(["delete", "job", job, "-n", ns, "--ignore-not-found"])

    k.apply_kustomize(job_path, ns)
    console.print(f"[green]✓[/green] Migration job '{job}' applied")

    result = k.run(
        ["wait", "--for=condition=complete", f"job/{job}", "-n", ns, f"--timeout={timeout}s"],
        capture=False,
    )
    if result.returncode != 0:
        console.print(f"[red]Migration failed or timed out.[/red]")
        console.print(f"Check logs: kubectl -n {ns} logs job/{job}")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Migration completed for {service} in {env_name}")


@app.command()
def connect(
    service: str = typer.Argument(..., help="Database service name (postgres, redis, mysql)"),
    env_name: str = typer.Option(..., help="Environment"),
    db: str = typer.Option(None, "--db", help="Database name to connect to"),
) -> None:
    """Open an interactive database session."""
    ns = f"env-{env_name}"
    pod = f"{service}-0"

    shell_cmd = _SHELLS.get(service)
    if not shell_cmd:
        console.print(f"[red]Unknown database service:[/red] {service}")
        console.print(f"Supported: {', '.join(_SHELLS.keys())}")
        raise typer.Exit(1)

    if db and service == "postgres":
        shell_cmd = shell_cmd + [db]

    kubectl_cmd = ["kubectl", "exec", "-it", pod, "-n", ns, "--"] + shell_cmd
    subprocess.run(kubectl_cmd)


@app.command()
def query(
    env_name: str = typer.Option(..., "--env", help="Environment"),
    db: str = typer.Option("postgres", "--db", help="Database name"),
    sql: str = typer.Argument(..., help="SQL query to run"),
) -> None:
    """Run a SQL query against Postgres in an environment."""
    ns = f"env-{env_name}"
    result = k.run([
        "exec", "postgres-0", "-n", ns, "--",
        "psql", "-U", "klight", "-d", db, "-c", sql,
    ])
    if result.returncode != 0:
        console.print(f"[red]Query failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(result.stdout)
