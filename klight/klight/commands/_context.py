"""Context validation — called before any destructive or cluster-targeting operation."""

import os
import subprocess
import typer
from rich.console import Console

console = Console()

_SAFE_PREFIXES = ("klight-",)
_SAFE_EXACT = {"minikube"}
_BYPASS_ENV_VAR = "KLIGHT_ALLOW_ANY_CONTEXT"


def assert_safe_context() -> None:
    """
    Verify the current kubectl context is a klight-safe target.

    Passes silently if the context name starts with 'klight-' or is exactly 'minikube'.
    Raises typer.Exit(1) for any other context, unless KLIGHT_ALLOW_ANY_CONTEXT=1 is set.
    """
    try:
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            text=True,
            capture_output=True,
        )
        ctx = result.stdout.strip()
    except FileNotFoundError:
        console.print("[bold red]Error:[/bold red] kubectl not found in PATH.")
        raise typer.Exit(1)

    if not ctx:
        console.print("[bold red]Error:[/bold red] No active kubectl context found.")
        raise typer.Exit(1)

    # Check if this is a safe context
    is_safe = ctx in _SAFE_EXACT or any(ctx.startswith(p) for p in _SAFE_PREFIXES)
    if is_safe:
        return

    # Check bypass env var
    if os.environ.get(_BYPASS_ENV_VAR) == "1":
        console.print(
            f"[bold yellow]Warning:[/bold yellow] KLIGHT_ALLOW_ANY_CONTEXT=1 — "
            f"operating on context '[yellow]{ctx}[/yellow]'. You accept responsibility."
        )
        return

    console.print(
        f"[bold red]Error:[/bold red] Current kubectl context is '[yellow]{ctx}[/yellow]'\n"
        f"klight only operates on contexts starting with 'klight-' or 'minikube'.\n"
        f"\nTo switch to a safe context:\n"
        f"  klight use local        (minikube / klight-demo)\n"
        f"  klight use klight-remote\n"
        f"\nTo override (DANGEROUS — you accept responsibility):\n"
        f"  export {_BYPASS_ENV_VAR}=1"
    )
    raise typer.Exit(1)
