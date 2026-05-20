import typer
from pathlib import Path
from typing import Optional
from klight.commands import env, service, db, profile, vault
from klight.commands import ps, unready, open_, exec_, local
from klight.commands import ui
from klight.commands import watch
from klight.commands import sync as sync_cmd
from klight.commands import replace as replace_cmd
from klight.commands import setup as setup_cmd
from klight.commands import target as target_cmd
from klight.commands import preflight

app = typer.Typer(
    name="klight",
    help="klight — Kubernetes environment manager for startups.",
    no_args_is_help=True,
)

# Core command groups
app.add_typer(env.app, name="env")
app.add_typer(service.app, name="service")
app.add_typer(db.app, name="db")
app.add_typer(profile.app, name="profile")
app.add_typer(vault.app, name="vault")
app.add_typer(local.app, name="local")
app.add_typer(target_cmd.app, name="cluster")


# --- Top-level dev-friendly commands (kcs-inspired UX) ---

@app.command()
def init(
    path: Path = typer.Argument(default=Path("."), help="Path to service repo"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Use detected defaults without prompting"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing klight.yaml"),
) -> None:
    """Scan a service repo and generate klight.yaml. No K8s knowledge required."""
    from klight.commands.init_ import cmd as init_cmd
    init_cmd(path, yes=yes, force=force)


@app.command(name="from-repos")
def from_repos(
    repos: list[Path] = typer.Argument(..., help="Paths to service repos with klight.yaml"),
    env_name: str = typer.Option(..., "--env", help="Target environment name"),
    timeout: int = typer.Option(300, "--timeout", help="Seconds to wait for all services"),
) -> None:
    """
    Deploy services from their klight.yaml files. No infra repo needed.

    Reads klight.yaml from each repo, auto-generates K8s manifests,
    spins up required infra (postgres, kafka...), and deploys all services
    in dependency order.

    Example:
      klight from-repos ./store-api ./inventory-api ./store-web --env alice
    """
    from klight.commands.repos import up_from_repos
    # Invoke directly with the args (repos is already a list of Paths)
    import sys
    from klight.commands.repos import _ensure_namespace, _sort_by_deps, _apply_manifest, _wait_job, _wait_deployment, _print_summary
    from klight.schema import KlightConfig, KNOWN_INFRA
    from klight import kubectl as k, manifest_gen
    from rich.console import Console
    console = Console()

    ns = f"env-{env_name}"

    configs: list[KlightConfig] = []
    for repo_path in repos:
        klf = repo_path.resolve() / "klight.yaml"
        if not klf.exists():
            console.print(f"[red]No klight.yaml in {repo_path}[/red]  →  run: klight init {repo_path}")
            raise typer.Exit(1)
        cfg = KlightConfig.from_file(klf)
        configs.append(cfg)
        console.print(f"[green]✓[/green] {klf.parent.name}/klight.yaml  [cyan]{cfg.name}[/cyan]:{cfg.port}  needs={cfg.needs or '[]'}")

    all_infra = set()
    for cfg in configs:
        all_infra.update(cfg.needs)
    all_infra = all_infra & KNOWN_INFRA.keys()

    console.print(f"\n[bold]Infra:[/bold] {', '.join(sorted(all_infra)) or 'none'}")
    _ensure_namespace(ns, env_name)

    manifests_dir = k.get_manifests_dir()
    for infra_name in sorted(all_infra):
        infra_path = manifests_dir / KNOWN_INFRA[infra_name]["manifest_dir"]
        if infra_path.exists():
            console.print(f"  deploying {infra_name}...")
            k.apply_kustomize(infra_path, ns)
        else:
            console.print(f"[yellow]  {infra_name}: manifest not found at {infra_path}[/yellow]")

    if all_infra:
        for infra_name in sorted(all_infra):
            k.run(["wait", "--for=condition=ready", f"pod/{infra_name}-0", "-n", ns, "--timeout=120s"], capture=False)

    ordered = _sort_by_deps(configs)

    for cfg in ordered:
        console.print(f"\n[bold]Deploying[/bold] {cfg.name}...")
        k.run(["delete", "job", f"{cfg.name}-migrate", "-n", ns, "--ignore-not-found"])
        for manifest in manifest_gen.all_manifests(cfg):
            _apply_manifest(manifest, ns)
        if cfg.migration:
            console.print(f"  waiting for migration...")
            if not _wait_job(f"{cfg.name}-migrate", ns):
                console.print(f"[red]  Migration failed.[/red]  kubectl logs -n {ns} job/{cfg.name}-migrate")
                raise typer.Exit(1)

    console.print(f"\n[bold]Waiting for all services...[/bold]")
    for cfg in ordered:
        _wait_deployment(cfg.name, ns, timeout=timeout)

    console.print(f"\n[bold green]Done! '{env_name}' is ready.[/bold green]")
    _print_summary(ordered, ns, env_name)


@app.command()
def ui_cmd(
    port: int = typer.Option(7700, "--port", "-p"),
    no_browser: bool = typer.Option(False, "--no-browser"),
) -> None:
    """Open the klight web dashboard (http://localhost:7700)."""
    from klight.commands.ui import cmd as ui_start
    ui_start(port=port, no_browser=no_browser)


# Rename so it shows as "klight ui" in help
ui_cmd.name = "ui"
app.command(name="ui")(lambda port=7700, no_browser=False: None)  # placeholder overridden below


@app.command(name="ui")
def ui_launch(
    port: int = typer.Option(7700, "--port", "-p", help="Port (default: 7700)"),
    no_browser: bool = typer.Option(False, "--no-browser"),
) -> None:
    """Open the klight web dashboard."""
    from klight.commands.ui import cmd as ui_start
    ui_start(port=port, no_browser=no_browser)


@app.command()
def ps(
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Pretty service status table. No pod hashes, no K8s jargon."""
    from klight.commands.ps import run
    run(env_name)


@app.command()
def unready(
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Show services that are not Ready, with a fix hint for each."""
    from klight.commands.unready import run
    all_ready = run(env_name)
    if not all_ready:
        raise typer.Exit(1)


@app.command(name="open")
def open_cmd(
    service_name: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    port: Optional[int] = typer.Option(None, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser"),
) -> None:
    """Port-forward a service to localhost and open it in the browser."""
    from klight.commands.open_ import cmd
    cmd(service_name, env_name=env_name, port=port, no_browser=no_browser)


@app.command(name="exec")
def exec_cmd(
    service_name: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    ctx: typer.Context = typer.Option(None),
) -> None:
    """Exec into a service pod by service name."""
    from klight.commands.exec_ import cmd
    cmd(service_name, env_name=env_name, ctx=ctx)


@app.command()
def up(
    profile_name: str = typer.Argument(..., help="Profile name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    timeout: int = typer.Option(300, "--timeout"),
) -> None:
    """Bring up all services in a profile (alias: klight profile up)."""
    from klight.commands.profile import up as profile_up
    profile_up(profile_name, env_name=env_name, timeout=timeout)


@app.command()
def down(
    profile_name: str = typer.Argument(..., help="Profile name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Scale down all services in a profile."""
    from klight.commands.profile import down as profile_down
    profile_down(profile_name, env_name=env_name)


@app.command()
def status(
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Show pod and job status for an environment."""
    from klight.commands.env import describe
    describe(env_name)


@app.command()
def logs(
    service_name: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    follow: bool = typer.Option(False, "-f", "--follow"),
    tail: int = typer.Option(100, "--tail"),
    since: Optional[str] = typer.Option(None, "--since"),
) -> None:
    """Stream logs from a service."""
    from klight.commands.service import logs as service_logs
    service_logs(service_name, env_name=env_name, follow=follow, tail=tail, since=since)



@app.command()
def watch_cmd(
    service: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    path: Path = typer.Option(None, "--path", help="Path to service repo"),
    profile: str = typer.Option("klight-demo", "--profile"),
) -> None:
    """Watch source files and rebuild + restart pod on every change (hot reload)."""
    from klight.commands.watch import cmd as watch_start
    watch_start(service, env_name=env_name, path=path, profile=profile)


@app.command()
def preflight(
    repos: list[Path] = typer.Argument(None, help="Service repo paths"),
    env_name: str = typer.Option("", "--env"),
    fix: bool = typer.Option(False, "--fix", help="Auto-build/pull missing images"),
    profile: str = typer.Option("klight-demo", "--profile"),
) -> None:
    """Check image availability before deploying. Use --fix to auto-resolve."""
    from klight.commands.preflight import cmd as pf_cmd
    pf_cmd(repos=repos, env_name=env_name, fix=fix, profile=profile)



@app.command(name="use")
def use_target(
    target: str = typer.Argument(..., help="Target: local, remote, or kubectl context name"),
) -> None:
    """Switch cluster target. klight use local / klight use remote"""
    from klight.commands.target import use_target as _use
    _use(target)


@app.command(name="target")
def show_target() -> None:
    """Show current cluster target (local/remote/custom)."""
    from klight.commands.target import show_target as _show
    _show()


@app.command(name="connect")
def connect_cluster(
    url: str = typer.Option("", "--url"),
    token: str = typer.Option("", "--token"),
    kubeconfig: Path = typer.Option(None, "--kubeconfig"),
    context_name: str = typer.Option("klight-remote", "--name"),
) -> None:
    """Configure access to a remote cluster."""
    from klight.commands.target import connect as _connect
    _connect(url=url, token=token, kubeconfig=kubeconfig, context_name=context_name)



@app.command()
def destroy(
    name: str = typer.Argument(..., help="Environment name to destroy"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an environment and all its resources."""
    from klight.commands.env import destroy as _destroy
    _destroy(name, yes=yes)


@app.command()
def sync(
    url: str = typer.Argument("", help="URL to klight-team.yaml"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Download and apply klight-team.yaml. Auto-syncs daily on klight up."""
    from klight.commands.sync import cmd as _sync
    _sync(url=url, force=force)


@app.command()
def replace(
    service: str = typer.Argument(..., help="Service to replace with local build"),
    env_name: str = typer.Option(..., "--env"),
    path: Path = typer.Option(Path("."), "--with", help="Path to service repo"),
    minikube_profile: str = typer.Option("klight-demo", "--profile"),
) -> None:
    """Replace a running service with a local build. Others keep CI images."""
    from klight.commands.replace import replace as _replace
    _replace(service=service, env_name=env_name, path=path, minikube_profile=minikube_profile)


@app.command()
def restore(
    service: str = typer.Argument(..., help="Service to restore to CI image"),
    env_name: str = typer.Option(..., "--env"),
    image: str = typer.Option("", "--image", help="Specific image (optional)"),
) -> None:
    """Restore a service to its CI image (undo klight replace)."""
    from klight.commands.replace import restore as _restore
    _restore(service=service, env_name=env_name, image=image)


@app.command()
def setup(
    token: str = typer.Option("", "--token", "-t", envvar="KLIGHT_SETUP_TOKEN"),
    org: str = typer.Option("", "--org", "-o"),
    platform: str = typer.Option("", "--platform"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Interactive setup wizard: connect platform, scan repos, generate klight.yaml files."""
    from klight.commands.setup import cmd as _setup
    _setup(token=token, org=org, platform=platform, yes=yes)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
