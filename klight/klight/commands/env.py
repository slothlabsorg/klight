import json
import subprocess
import typer
from rich.console import Console
from rich.table import Table
from klight import kubectl as k

app = typer.Typer(help="Environment lifecycle: create, destroy, list, pause, resume.")
console = Console()


def _ns(name: str) -> str:
    return f"env-{name}"


@app.command()
def create(
    name: str = typer.Argument(..., help="Environment name (e.g. alice, pr-123)"),
    with_infra: bool = typer.Option(False, "--with-infra", help="Deploy Postgres and Redis"),
    with_vault: bool = typer.Option(False, "--with-vault", help="Deploy Vault and run init"),
    profile_name: str = typer.Option(None, "--profile", help="Run named profile after infra"),
) -> None:
    """Create a new isolated environment (Kubernetes namespace)."""
    ns = _ns(name)
    manifests = k.get_manifests_dir()

    result = k.run(["create", "namespace", ns])
    if result.returncode != 0 and "already exists" not in result.stderr:
        console.print(f"[red]Error creating namespace:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Namespace {ns}")

    k.run(["label", "namespace", ns, f"klight.env={name}", "--overwrite"])

    config_path = manifests / "env" / "config"
    k.apply_kustomize(config_path, ns)
    console.print("[green]✓[/green] Global config")

    secrets_path = manifests / "env" / "secrets"
    secrets_env = secrets_path / "global.env"
    if secrets_env.exists():
        k.apply_kustomize(secrets_path, ns)
        console.print("[green]✓[/green] Global secrets")
    else:
        console.print(
            "[yellow]![/yellow] No secrets/global.env found — skipping. "
            "Copy manifests/env/secrets/global.env.example to global.env and fill in values."
        )

    if with_infra:
        for infra in ["postgres", "redis"]:
            infra_path = manifests / "infrastructure" / infra / "base"
            k.apply_kustomize(infra_path, ns)
            console.print(f"[green]✓[/green] {infra}")

    if with_vault:
        vault_path = manifests / "infrastructure" / "vault" / "base"
        k.apply_kustomize(vault_path, ns)
        console.print("[green]✓[/green] vault")

    console.print(f"\n[bold green]Environment '{name}' created.[/bold green]")
    console.print(f"  Namespace: [cyan]{ns}[/cyan]")
    console.print(f"  Watch:     kubectl -n {ns} get pods -w")
    if profile_name:
        console.print(f"\nRunning profile '{profile_name}'...")
        from klight.commands.profile import up
        up(profile_name, env_name=name)


@app.command()
def destroy(
    name: str = typer.Argument(..., help="Environment name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Destroy an environment and all its resources. Irreversible."""
    from klight.commands._context import assert_safe_context
    assert_safe_context()
    ns = _ns(name)
    if not yes:
        typer.confirm(
            f"Destroy environment '{name}' (namespace: {ns})? "
            "All data including databases will be lost.",
            abort=True,
        )
    result = k.run(["delete", "namespace", ns, "--ignore-not-found"])
    if result.returncode != 0:
        console.print(f"[red]Error:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Environment '{name}' destroyed.")


@app.command(name="list")
def list_envs() -> None:
    """List all active klight environments."""
    data = k.run_json(["get", "namespaces", "-l", "klight.env"])
    if not data or not data.get("items"):
        console.print("No environments found.")
        return

    table = Table(title="Environments")
    table.add_column("Name", style="cyan")
    table.add_column("Namespace")
    table.add_column("Status")
    table.add_column("Age")

    for item in data["items"]:
        env_name = item["metadata"]["labels"]["klight.env"]
        ns = item["metadata"]["name"]
        status = item["status"]["phase"]
        creation = item["metadata"]["creationTimestamp"]
        table.add_row(env_name, ns, status, creation)

    console.print(table)


@app.command()
def describe(
    name: str = typer.Argument(..., help="Environment name"),
) -> None:
    """Show all pods and jobs in an environment."""
    ns = _ns(name)
    console.print(f"\n[bold]Environment:[/bold] {name} (namespace: {ns})\n")

    result = k.run(["get", "pods", "-n", ns])
    if result.returncode == 0:
        console.print("[bold]Pods:[/bold]")
        console.print(result.stdout)

    result = k.run(["get", "jobs", "-n", ns])
    if result.returncode == 0 and result.stdout.strip() != "No resources found in default namespace.":
        console.print("[bold]Jobs:[/bold]")
        console.print(result.stdout)


@app.command()
def pause(
    name: str = typer.Argument(..., help="Environment name"),
) -> None:
    """Scale all Deployments to 0. Databases and PVCs are preserved."""
    ns = _ns(name)
    data = k.run_json(["get", "deployments", "-n", ns])
    if not data or not data.get("items"):
        console.print("No deployments found.")
        return
    for item in data["items"]:
        dep_name = item["metadata"]["name"]
        k.run(["scale", "deployment", dep_name, "--replicas=0", "-n", ns])
        console.print(f"[green]✓[/green] Scaled down {dep_name}")
    console.print(f"\n[yellow]Environment '{name}' paused.[/yellow] Resume with: klight env resume {name}")


@app.command()
def resume(
    name: str = typer.Argument(..., help="Environment name"),
) -> None:
    """Scale all Deployments back to 1 replica."""
    ns = _ns(name)
    data = k.run_json(["get", "deployments", "-n", ns])
    if not data or not data.get("items"):
        console.print("No deployments found.")
        return
    for item in data["items"]:
        dep_name = item["metadata"]["name"]
        k.run(["scale", "deployment", dep_name, "--replicas=1", "-n", ns])
        console.print(f"[green]✓[/green] Resumed {dep_name}")
    console.print(f"\n[green]Environment '{name}' resumed.[/green]")
