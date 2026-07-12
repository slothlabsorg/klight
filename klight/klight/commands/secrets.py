"""
klight secrets — per-service secrets management.

Materializes a per-service Kubernetes Secret named `{service}-secrets` in the
environment namespace. Services opt in by listing keys under `secrets:` in their
klight.yaml; klight mounts that Secret via an (optional) secretRef, so the
service runs in mock mode until secrets are set.

Usage:
  klight secrets set students-api AUTH0_CLIENT_SECRET=xyz --env dev
  klight secrets set notifications-api SENDGRID_API_KEY=... TWILIO_AUTH_TOKEN=... --env alice
  klight secrets set orders-grpc --env tl --from-env ./.env.local
  klight secrets list students-api --env dev
  klight secrets unset students-api AUTH0_CLIENT_SECRET --env dev
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from klight import kubectl as k

app = typer.Typer(help="Manage per-service secrets ({service}-secrets).")
console = Console()


def _secret_name(service: str) -> str:
    return f"{service}-secrets"


def _read_existing(ns: str, name: str) -> dict[str, str]:
    """Return current {key: plaintext} from the Secret, or {} if absent."""
    data = k.run_json(["get", "secret", name, "-n", ns])
    if not data:
        return {}
    out: dict[str, str] = {}
    for key, b64 in (data.get("data") or {}).items():
        try:
            out[key] = base64.b64decode(b64).decode("utf-8")
        except Exception:
            out[key] = ""
    return out


def _apply_secret(ns: str, name: str, values: dict[str, str]) -> None:
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "labels": {"klight.managed": "true"}},
        "type": "Opaque",
        "stringData": {key: str(val) for key, val in values.items()},
    }
    k.apply_manifest_dict(manifest, ns)


def _parse_pairs(pairs: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            console.print(f"[red]Invalid KEY=VALUE:[/red] {pair}")
            raise typer.Exit(1)
        key, val = pair.split("=", 1)
        parsed[key.strip()] = val
    return parsed


def _parse_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        parsed[key.strip()] = val.strip().strip('"').strip("'")
    return parsed


@app.command()
def set(
    service: str = typer.Argument(..., help="Service name"),
    pairs: list[str] = typer.Argument(None, help="KEY=VALUE pairs"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    from_env: Optional[Path] = typer.Option(None, "--from-env", help="Load KEY=VALUE from a .env file"),
) -> None:
    """Set one or more secrets for a service (merges with existing keys)."""
    ns = f"env-{env_name}"
    if not k.namespace_exists(ns):
        console.print(f"[red]Environment '{env_name}' not found[/red] (namespace {ns}).")
        console.print("Create it first: klight env create " + env_name)
        raise typer.Exit(1)

    new_values: dict[str, str] = {}
    if from_env:
        if not from_env.exists():
            console.print(f"[red]File not found:[/red] {from_env}")
            raise typer.Exit(1)
        new_values.update(_parse_env_file(from_env))
    if pairs:
        new_values.update(_parse_pairs(pairs))

    if not new_values:
        console.print("[yellow]Nothing to set.[/yellow] Pass KEY=VALUE or --from-env.")
        raise typer.Exit(1)

    name = _secret_name(service)
    merged = _read_existing(ns, name)
    merged.update(new_values)
    _apply_secret(ns, name, merged)

    keys = ", ".join(sorted(new_values.keys()))
    console.print(f"[green]✓[/green] Set {len(new_values)} secret(s) on [bold]{name}[/bold]: {keys}")
    console.print(f"  Apply to the running pod: klight replace {service} --with <path> --env {env_name}")


@app.command(name="list")
def list_(
    service: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """List the secret KEYS set for a service (values are never printed)."""
    ns = f"env-{env_name}"
    name = _secret_name(service)
    values = _read_existing(ns, name)
    if not values:
        console.print(f"[dim]No secrets set for {service} in {env_name}.[/dim]")
        return
    console.print(f"[bold]{name}[/bold] ({len(values)} keys):")
    for key in sorted(values.keys()):
        console.print(f"  • {key}")


@app.command()
def unset(
    service: str = typer.Argument(..., help="Service name"),
    keys: list[str] = typer.Argument(..., help="Keys to remove"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
) -> None:
    """Remove one or more secret keys from a service."""
    ns = f"env-{env_name}"
    name = _secret_name(service)
    values = _read_existing(ns, name)
    if not values:
        console.print(f"[dim]No secrets set for {service} in {env_name}.[/dim]")
        return
    removed = [key for key in keys if values.pop(key, None) is not None]
    if not removed:
        console.print("[yellow]No matching keys.[/yellow]")
        return
    if values:
        _apply_secret(ns, name, values)
    else:
        k.run(["delete", "secret", name, "-n", ns, "--ignore-not-found"])
    console.print(f"[green]✓[/green] Removed: {', '.join(removed)}")
