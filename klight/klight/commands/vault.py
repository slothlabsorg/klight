import os
import subprocess
import typer
from pathlib import Path
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Vault management (init, seed secrets).")
console = Console()


@app.command()
def init(
    env_name: str = typer.Option(..., "--env", help="Environment"),
) -> None:
    """Initialize and unseal Vault in dev mode. Stores root token as a K8s Secret."""
    ns = f"env-{env_name}"
    console.print("Waiting for Vault pod...")
    k.run(["wait", "--for=condition=ready", "pod/vault-0", "-n", ns, "--timeout=60s"], capture=False)

    # Vault dev mode starts pre-initialized and unsealed. Just store the token.
    token = "dev-root-token"  # matches VAULT_DEV_ROOT_TOKEN_ID in StatefulSet
    result = k.run([
        "create", "secret", "generic", "klight-vault-token",
        f"--from-literal=token={token}",
        "-n", ns,
        "--dry-run=client", "-o", "yaml",
    ])
    if result.returncode == 0:
        apply_result = subprocess.run(
            ["kubectl", "apply", "-n", ns, "-f", "-"],
            input=result.stdout, text=True, capture_output=True,
        )
        if apply_result.returncode != 0:
            console.print(f"[red]Error saving vault token:[/red] {apply_result.stderr}")
            raise typer.Exit(1)

    # Enable KV v2 engine
    vault_exec(ns, ["vault", "secrets", "enable", "-version=2", "kv"])
    console.print(f"[green]✓[/green] Vault initialized in {env_name}")
    console.print(f"  Token: {token}  (dev only — do not use in production)")
    console.print(f"  UI:    kubectl -n {ns} port-forward svc/vault 8200:8200")


@app.command()
def seed(
    env_name: str = typer.Option(..., "--env", help="Environment"),
    file: Path = typer.Option(None, "--file", help="Path to .env file with KEY=VALUE secrets"),
    from_ci_env: list[str] = typer.Option([], "--from-ci-env", help="Env var names to pull from current shell"),
) -> None:
    """Seed secrets into Vault from a .env file or current environment variables."""
    ns = f"env-{env_name}"
    secrets: dict[str, str] = {}

    if file:
        if not file.exists():
            console.print(f"[red]File not found:[/red] {file}")
            raise typer.Exit(1)
        for line in file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            secrets[key.strip()] = value.strip()

    for key in from_ci_env:
        value = os.environ.get(key)
        if value is None:
            console.print(f"[yellow]Warning:[/yellow] {key} not set in environment, skipping")
            continue
        secrets[key] = value

    if not secrets:
        console.print("[yellow]No secrets to seed.[/yellow]")
        return

    kv_args = [f"{k}={v}" for k, v in secrets.items()]
    vault_exec(ns, ["vault", "kv", "put", "kv/global"] + kv_args)
    console.print(f"[green]✓[/green] Seeded {len(secrets)} secrets to kv/global in {env_name}")


def vault_exec(ns: str, cmd: list[str]) -> None:
    result = k.run([
        "exec", "vault-0", "-n", ns, "--",
        "sh", "-c",
        f"VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=dev-root-token {' '.join(cmd)}",
    ])
    if result.returncode != 0:
        console.print(f"[red]Vault command failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
