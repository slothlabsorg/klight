"""
klight aws-refresh — One-command AWS credential refresh for all services.

Checks the current SSO session, refreshes if expired, exports credentials,
pushes them into per-service Kubernetes Secrets, and triggers a rolling restart
so pods pick up the new creds immediately.

Usage:
  klight aws-refresh --profile my-sso-profile --env dev
  klight aws-refresh --profile my-sso-profile --env alice --services orders-grpc notifications-api
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from klight import kubectl as k

app = typer.Typer(help="Refresh AWS credentials for services in an environment.")
console = Console()


def _sso_session_valid(profile: str) -> bool:
    """Return True if the SSO session for the given profile is still active."""
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--profile", profile],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _sso_login(profile: str) -> None:
    """Run aws sso login interactively."""
    console.print(f"[yellow]SSO session expired.[/yellow] Launching login for profile [bold]{profile}[/bold]...")
    result = subprocess.run(
        ["aws", "sso", "login", "--profile", profile],
        text=True,
    )
    if result.returncode != 0:
        console.print("[red]SSO login failed.[/red]")
        raise typer.Exit(1)
    console.print("[green]✓[/green] SSO login successful.")


def _export_credentials(profile: str) -> dict[str, str]:
    """
    Export fresh credentials from the profile in env-no-export format.
    Returns a dict of KEY=VALUE pairs (AWS_ACCESS_KEY_ID, etc.).
    """
    result = subprocess.run(
        ["aws", "configure", "export-credentials", "--profile", profile, "--format", "env-no-export"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Failed to export credentials:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        creds[key.strip()] = val.strip()

    if not creds:
        console.print("[red]No credentials exported.[/red] Check your AWS profile configuration.")
        raise typer.Exit(1)

    return creds


def _write_temp_env_file(creds: dict[str, str]) -> Path:
    """Write credentials to a temporary .env file for klight secrets set --from-env."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", prefix="klight-aws-creds-", delete=False
    )
    for key, val in creds.items():
        tmp.write(f"{key}={val}\n")
    tmp.close()
    return Path(tmp.name)


def _get_services_in_env(env_name: str) -> list[str]:
    """Discover all services (deployments) in the environment namespace."""
    ns = f"env-{env_name}"
    data = k.run_json(["get", "deployments", "-n", ns])
    if not data or not data.get("items"):
        return []
    services: list[str] = []
    for item in data["items"]:
        name = item["metadata"]["name"]
        services.append(name)
    return sorted(services)


def _set_secrets_for_service(service: str, env_name: str, env_file: Path) -> bool:
    """Set AWS credentials as secrets for a service. Returns True on success."""
    from klight.commands.secrets import _secret_name, _read_existing, _apply_secret, _parse_env_file

    ns = f"env-{env_name}"
    if not k.namespace_exists(ns):
        return False

    new_values = _parse_env_file(env_file)
    name = _secret_name(service)
    merged = _read_existing(ns, name)
    merged.update(new_values)
    _apply_secret(ns, name, merged)
    return True


def _restart_deployment(service: str, env_name: str) -> bool:
    """Trigger a rollout restart for the service deployment."""
    ns = f"env-{env_name}"
    result = k.run(["rollout", "restart", f"deployment/{service}", "-n", ns])
    return result.returncode == 0


@app.command()
def refresh(
    profile: str = typer.Option(..., "--profile", "-p", help="AWS SSO profile name"),
    env_name: str = typer.Option(..., "--env", help="Target environment name"),
    services: Optional[list[str]] = typer.Option(
        None, "--services", "-s", help="Service names to update (default: all in env)"
    ),
) -> None:
    """
    Refresh AWS credentials and push them to services.

    1. Validates SSO session (logs in if expired)
    2. Exports fresh credentials
    3. Updates per-service secrets
    4. Triggers rolling restart for affected pods
    """
    ns = f"env-{env_name}"
    if not k.namespace_exists(ns):
        console.print(f"[red]Environment '{env_name}' not found[/red] (namespace {ns}).")
        console.print(f"Create it first: klight env create {env_name}")
        raise typer.Exit(1)

    # Step 1: Check / refresh SSO session
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Checking SSO session...", total=None)

        if _sso_session_valid(profile):
            progress.update(task, description="[green]SSO session valid[/green]")
            console.print(f"[green]✓[/green] SSO session for [bold]{profile}[/bold] is valid.")
        else:
            progress.stop()
            _sso_login(profile)

    # Step 2: Export fresh credentials
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Exporting credentials...", total=None)
        creds = _export_credentials(profile)
        progress.update(task, description="[green]Credentials exported[/green]")

    console.print(f"[green]✓[/green] Exported {len(creds)} credential variable(s): {', '.join(sorted(creds.keys()))}")

    # Write creds to temp file
    env_file = _write_temp_env_file(creds)

    try:
        # Resolve target services
        target_services = services if services else _get_services_in_env(env_name)
        if not target_services:
            console.print(f"[yellow]No services found in environment '{env_name}'.[/yellow]")
            raise typer.Exit(0)

        console.print(f"\nUpdating [bold]{len(target_services)}[/bold] service(s) in [cyan]{env_name}[/cyan]:\n")

        # Step 3 & 4: Update secrets and restart for each service
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for svc in target_services:
                task = progress.add_task(f"  {svc}: setting secrets...", total=None)

                success = _set_secrets_for_service(svc, env_name, env_file)
                if success:
                    progress.update(task, description=f"  {svc}: restarting pod...")
                    restarted = _restart_deployment(svc, env_name)
                    if restarted:
                        progress.update(task, description=f"  [green]✓[/green] {svc}: secrets updated, restart triggered")
                    else:
                        progress.update(task, description=f"  [yellow]⚠[/yellow] {svc}: secrets updated, restart failed")
                else:
                    progress.update(task, description=f"  [red]✗[/red] {svc}: failed to set secrets")

                progress.remove_task(task)
                # Print final status line (visible after progress clears)
                if success and restarted:
                    console.print(f"  [green]✓[/green] {svc}")
                elif success:
                    console.print(f"  [yellow]⚠[/yellow] {svc} (secrets set, restart failed)")
                else:
                    console.print(f"  [red]✗[/red] {svc} (failed)")

        console.print(f"\n[bold green]Done![/bold green] AWS credentials refreshed for {len(target_services)} service(s).")
        console.print(f"  Monitor rollout: kubectl -n {ns} get pods -w")

    finally:
        # Clean up temp file
        env_file.unlink(missing_ok=True)
