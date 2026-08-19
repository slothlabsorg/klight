"""
klight mode — Toggle between LOCAL and REMOTE backend modes.

Reads/writes ~/.devnext-mode, the same file that custom reverse proxies read
to decide whether to route traffic locally or to the real dev environment.

Usage:
  klight mode          # show current mode
  klight mode local    # switch to LOCAL
  klight mode remote   # switch to REMOTE
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(help="Toggle between LOCAL and REMOTE backend modes.")
console = Console()

MODE_FILE = Path.home() / ".devnext-mode"

VALID_MODES = ("local", "remote")

MODE_DESCRIPTIONS = {
    "remote": (
        "[bold cyan]REMOTE[/bold cyan] — Secondary services (chat, notification, addressbook) "
        "proxy to the real dev environment with token swap.\n"
        "  • Lightweight on local resources\n"
        "  • Only your target service runs locally\n"
        "  • Depends on dev environment availability"
    ),
    "local": (
        "[bold green]LOCAL[/bold green] — All services run locally in klight. Full stack.\n"
        "  • Complete isolation, no external dependencies\n"
        "  • Full stack available for integration testing\n"
        "  • Heavier on CPU/memory"
    ),
}


def _read_mode() -> str:
    """Read current mode from ~/.devnext-mode. Defaults to 'remote' if missing."""
    if not MODE_FILE.exists():
        return "remote"
    content = MODE_FILE.read_text().strip().lower()
    if content in VALID_MODES:
        return content
    return "remote"


def _write_mode(mode: str) -> None:
    """Write mode to ~/.devnext-mode."""
    MODE_FILE.write_text(mode.upper() + "\n")


def _print_mode_info(mode: str) -> None:
    """Print a description of what the given mode means."""
    console.print()
    console.print(Panel(
        MODE_DESCRIPTIONS.get(mode, "Unknown mode"),
        title=f"Mode: {mode.upper()}",
        border_style="cyan" if mode == "remote" else "green",
    ))


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    mode: Optional[str] = typer.Argument(None, help="Mode to switch to: local or remote"),
) -> None:
    """
    Show or switch the backend mode (LOCAL / REMOTE).

    Without arguments, shows the current mode.
    With an argument, switches to the specified mode.
    """
    if ctx.invoked_subcommand is not None:
        return

    if mode is None:
        # Show current mode
        current = _read_mode()
        console.print(f"\nCurrent mode: [bold]{current.upper()}[/bold]")
        _print_mode_info(current)
        console.print(f"\n[dim]Config file: {MODE_FILE}[/dim]")
        console.print("[dim]Switch with: klight mode local | klight mode remote[/dim]\n")
        return

    # Validate
    mode_lower = mode.lower()
    if mode_lower not in VALID_MODES:
        console.print(f"[red]Invalid mode:[/red] '{mode}'")
        console.print(f"Valid modes: {', '.join(VALID_MODES)}")
        raise typer.Exit(1)

    # Check if already in requested mode
    current = _read_mode()
    if current == mode_lower:
        console.print(f"\n[yellow]Already in {mode_lower.upper()} mode.[/yellow] Nothing to change.")
        _print_mode_info(mode_lower)
        return

    # Switch
    old_mode = current
    _write_mode(mode_lower)
    console.print(f"\n[green]✓[/green] Switched mode: [bold]{old_mode.upper()}[/bold] → [bold]{mode_lower.upper()}[/bold]")
    _print_mode_info(mode_lower)
    console.print(f"\n[dim]Written to: {MODE_FILE}[/dim]")

    # Hint about what to do next
    if mode_lower == "local":
        console.print("\n[dim]Tip: Run 'klight up <profile> --env <env>' to start the full local stack.[/dim]\n")
    else:
        console.print("\n[dim]Tip: Proxies will route secondary services to dev on next request.[/dim]\n")
