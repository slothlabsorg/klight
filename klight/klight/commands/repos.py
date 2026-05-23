"""
klight up --from-repos — reads klight.yaml from each service repo,
auto-generates K8s manifests, and deploys everything.

No infra repo needed. No K8s YAML needed. Just klight.yaml per service.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich import box

from klight import kubectl as k, catalog as cat
from klight.schema import KlightConfig

app = typer.Typer()
console = Console()


def _apply_manifest(manifest: dict, namespace: str) -> bool:
    """Apply a single K8s manifest dict via kubectl apply -f -"""
    result = subprocess.run(
        ["kubectl", "apply", "-n", namespace, "-f", "-"],
        input=json.dumps(manifest),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Error applying {manifest['kind']}/{manifest['metadata']['name']}:[/red]")
        console.print(result.stderr.strip())
        return False
    action = result.stdout.strip().split(" ")[-1]  # created / configured / unchanged
    console.print(f"  [dim]{manifest['kind']}/{manifest['metadata']['name']}[/dim] {action}")
    return True


def _wait_job(name: str, namespace: str, timeout: int = 120) -> bool:
    result = k.run([
        "wait", "--for=condition=complete", f"job/{name}",
        "-n", namespace, f"--timeout={timeout}s",
    ])
    return result.returncode == 0


def _wait_deployment(name: str, namespace: str, timeout: int = 180) -> bool:
    result = k.run([
        "rollout", "status", f"deployment/{name}",
        "-n", namespace, f"--timeout={timeout}s",
    ])
    return result.returncode == 0


@app.command(name="from-repos")
def up_from_repos(
    repos: list[Path] = typer.Argument(..., help="Paths to service repos with klight.yaml"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    timeout: int = typer.Option(300, "--timeout", help="Seconds to wait for all services"),
) -> None:
    """
    Deploy services from their klight.yaml files. No infra repo needed.

    Example:
      klight from-repos ./store-api ./inventory-api ./store-web --env alice
    """
    from klight.commands._context import assert_safe_context
    assert_safe_context()
    ns = f"env-{env_name}"

    # Load all klight.yaml files
    configs: list[KlightConfig] = []
    for repo_path in repos:
        klf = repo_path.resolve() / "klight.yaml"
        if not klf.exists():
            console.print(f"[red]No klight.yaml in {repo_path}[/red]")
            console.print(f"  Run: klight init {repo_path}")
            raise typer.Exit(1)
        cfg = KlightConfig.from_file(klf)
        configs.append(cfg)
        console.print(f"[green]✓[/green] Loaded {klf.parent.name}/klight.yaml → [cyan]{cfg.name}[/cyan]:{cfg.port}")

    # Resolve all infra needed across all services
    all_infra: set[str] = set()
    for cfg in configs:
        for need in cfg.needs:
            all_infra.add(need.name if hasattr(need, "name") else str(need))
    all_infra = all_infra & cat.load().keys()

    console.print(f"\n[bold]Infra needed:[/bold] {', '.join(sorted(all_infra)) or 'none'}")

    # Ensure namespace + global config exists
    _ensure_namespace(ns, env_name)

    # Deploy infra StatefulSets (if not already running)
    from klight import kubectl as kctl
    manifests_dir = kctl.get_manifests_dir()
    for infra_name in sorted(all_infra):
        infra_path = manifests_dir / cat.manifest_dir(infra_name)
        if infra_path.exists():
            console.print(f"\n  Deploying {infra_name}...")
            k.apply_kustomize(infra_path, ns)
        else:
            console.print(f"[yellow]  Warning: no manifest for {infra_name} at {infra_path}[/yellow]")
            console.print(f"  Create it or add --skip-infra to skip")

    # Wait for infra to be ready
    if all_infra:
        console.print(f"\n  Waiting for infra pods...")
        for infra_name in sorted(all_infra):
            pod_name = f"{infra_name}-0"
            k.run(["wait", "--for=condition=ready", f"pod/{pod_name}",
                   "-n", ns, "--timeout=120s"], capture=False)

    # Sort configs by dependency order (simple topological sort)
    ordered = _sort_by_deps(configs)

    # Deploy each service in order
    from klight import manifest_gen
    for cfg in ordered:
        console.print(f"\n[bold]Deploying[/bold] {cfg.name}...")

        # Delete old migration job if exists (to allow re-run)
        k.run(["delete", "job", f"{cfg.name}-migrate", "-n", ns, "--ignore-not-found"])

        # Check if service has its own K8s manifests
        if manifest_gen.has_own_manifest(cfg):
            manifest_path = manifest_gen.resolve_manifest_path(cfg)
            console.print(f"  [dim]Using existing manifests:[/dim] {manifest_path}")
            k.apply_kustomize(manifest_path, ns)
        else:
            # Generate manifests from klight.yaml
            for manifest in manifest_gen.all_manifests(cfg):
                _apply_manifest(manifest, ns)

        # Wait for migration job if declared
        if cfg.migration:
            console.print(f"  Waiting for migration...")
            if not _wait_job(f"{cfg.name}-migrate", ns):
                console.print(f"[red]  Migration failed for {cfg.name}[/red]")
                console.print(f"  kubectl logs -n {ns} job/{cfg.name}-migrate")
                raise typer.Exit(1)
            console.print(f"  [green]Migration complete[/green]")

    # Final health check
    console.print(f"\n[bold]Waiting for all services to be ready...[/bold]")
    all_ok = True
    for cfg in ordered:
        if not _wait_deployment(cfg.name, ns, timeout=timeout):
            console.print(f"[red]  {cfg.name} not ready after {timeout}s[/red]")
            all_ok = False

    if all_ok:
        console.print(f"\n[bold green]All services ready in '{env_name}'![/bold green]")
        _print_summary(ordered, ns, env_name)
    else:
        console.print(f"\n[yellow]Some services are not ready. Check:[/yellow]")
        console.print(f"  klight ps --env {env_name}")
        console.print(f"  klight unready --env {env_name}")
        raise typer.Exit(1)


def _ensure_namespace(ns: str, env_name: str) -> None:
    """Create namespace and apply global config if not already present."""
    result = k.run(["get", "namespace", ns])
    if result.returncode != 0:
        k.run(["create", "namespace", ns])
        k.run(["label", "namespace", ns, f"klight.env={env_name}", "--overwrite"])
        console.print(f"[green]✓[/green] Created namespace {ns}")

    from klight import kubectl as kctl
    manifests_dir = kctl.get_manifests_dir()
    config_path = manifests_dir / "env" / "config"
    secrets_path = manifests_dir / "env" / "secrets"

    if config_path.exists():
        k.apply_kustomize(config_path, ns)

    if (secrets_path / "global.env").exists():
        k.apply_kustomize(secrets_path, ns)
    else:
        console.print("[yellow]No secrets/global.env — skipping. DB passwords may be missing.[/yellow]")


def _sort_by_deps(configs: list[KlightConfig]) -> list[KlightConfig]:
    """
    Sort services so that dependencies come before dependents.
    Simple approach: if cfg A's depends mentions cfg B's name, B comes first.
    """
    name_map = {cfg.name: cfg for cfg in configs}
    ordered = []
    visited = set()

    def visit(cfg: KlightConfig) -> None:
        if cfg.name in visited:
            return
        # Visit dependencies first
        for dep in cfg.depends:
            dep_name = dep.split(":")[0]
            if dep_name in name_map:
                visit(name_map[dep_name])
        visited.add(cfg.name)
        ordered.append(cfg)

    for cfg in configs:
        visit(cfg)

    return ordered


def _print_summary(configs: list[KlightConfig], ns: str, env_name: str) -> None:
    table = Table(box=box.ROUNDED)
    table.add_column("Service", style="cyan")
    table.add_column("Port")
    table.add_column("Health")
    table.add_column("Access")

    for cfg in configs:
        table.add_row(
            cfg.name,
            str(cfg.port),
            cfg.health,
            f"klight open {cfg.name} --env {env_name}",
        )

    console.print(table)
    console.print(f"\n[dim]klight ps --env {env_name}[/dim]")
    console.print(f"[dim]klight ui[/dim]")
