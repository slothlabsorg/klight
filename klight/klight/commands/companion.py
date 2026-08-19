"""
klight companion — Non-k8s process management for local development.

Manages companion processes (UIs, watchers, bundlers) that run alongside
k8s services but are not themselves containerized.

Reads config from klight-companions.yaml, klight-team.yaml,
or the KLIGHT_LOCAL_PROCESSES_FILE env var (backwards compat).

Usage:
  klight companion start [name]
  klight companion stop [name]
  klight companion restart [name]
  klight companion status
  klight companion logs [name]
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import yaml
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Manage companion processes (UIs, watchers, bundlers).")
console = Console()

_KLIGHT_DIR = Path.home() / ".klight"
_PID_FILE = _KLIGHT_DIR / "companions.pid"
_LOGS_DIR = _KLIGHT_DIR / "companion-logs"


# --- Config loading ---

def _find_companion_config() -> dict | None:
    """Search for companion config from multiple sources."""
    search_paths: list[Path] = []

    # Env var override (backwards compat with KLIGHT_LOCAL_PROCESSES_FILE)
    env_path = os.environ.get("KLIGHT_LOCAL_PROCESSES_FILE")
    if env_path:
        search_paths.append(Path(env_path).expanduser())

    # Also support KLIGHT_COMPANIONS_FILE
    env_path2 = os.environ.get("KLIGHT_COMPANIONS_FILE")
    if env_path2:
        search_paths.append(Path(env_path2).expanduser())

    # Standard search locations
    search_paths.extend([
        Path.cwd() / "klight-companions.yaml",
        Path.cwd() / "klight-team.yaml",
        _KLIGHT_DIR / "teams" / "klight-companions.yaml",
        _KLIGHT_DIR / "teams" / "klight-team.yaml",
    ])

    for p in search_paths:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text())
                if data and "companions" in data:
                    return data["companions"]
            except Exception:
                continue

    return None


def _load_pids() -> dict[str, int]:
    """Load stored PIDs from file."""
    if _PID_FILE.exists():
        try:
            return json.loads(_PID_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_pids(pids: dict[str, int]) -> None:
    """Save PIDs to file."""
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(json.dumps(pids, indent=2))


def _is_running(pid: int) -> bool:
    """Check if a process is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_nvm_dir() -> Path | None:
    """Get NVM directory."""
    nvm_dir = os.environ.get("NVM_DIR")
    if nvm_dir:
        return Path(nvm_dir)
    default = Path.home() / ".nvm"
    if default.exists():
        return default
    return None


def _build_nvm_command(node_version: int | str, cmd: str) -> str:
    """Wrap a command with nvm use for the specified node version."""
    nvm_dir = _get_nvm_dir()
    if nvm_dir:
        # Source nvm and use the specified version
        nvm_script = nvm_dir / "nvm.sh"
        if nvm_script.exists():
            return f'source "{nvm_script}" && nvm use {node_version} --silent && {cmd}'
    # Fallback: try using the command directly
    return cmd


def _get_log_file(name: str) -> Path:
    """Get log file path for a companion."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return _LOGS_DIR / f"{name}.log"


def _check_port(port: int) -> bool:
    """Check if a port is listening."""
    import socket
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def _start_companion(name: str, config: dict) -> int | None:
    """Start a single companion process. Returns PID or None on failure."""
    label = config.get("label", name)
    cmd = config.get("cmd", "")
    cwd = config.get("cwd", ".")
    node_version = config.get("node")
    port = config.get("port")

    if not cmd:
        console.print(f"[red]No command defined for '{name}'[/red]")
        return None

    # Expand paths
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.exists():
        console.print(f"[yellow]Warning: cwd does not exist for '{name}': {cwd_path}[/yellow]")
        console.print(f"[dim]  Creating directory...[/dim]")
        cwd_path.mkdir(parents=True, exist_ok=True)

    # Check if port is already in use
    if port and _check_port(port):
        console.print(f"[yellow]Port {port} already in use for '{label}'. Skipping.[/yellow]")
        return None

    # Build the command
    if node_version:
        shell_cmd = _build_nvm_command(node_version, cmd)
    else:
        shell_cmd = cmd

    # Open log file
    log_file = _get_log_file(name)
    log_fd = open(log_file, "a")
    log_fd.write(f"\n{'='*60}\n")
    log_fd.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting: {label}\n")
    log_fd.write(f"  Command: {cmd}\n")
    log_fd.write(f"  CWD: {cwd_path}\n")
    if node_version:
        log_fd.write(f"  Node: {node_version}\n")
    log_fd.write(f"{'='*60}\n\n")
    log_fd.flush()

    try:
        proc = subprocess.Popen(
            shell_cmd,
            shell=True,
            executable="/bin/bash",
            cwd=str(cwd_path),
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,  # Detach from parent
            env={**os.environ, "FORCE_COLOR": "1"},
        )
        return proc.pid
    except Exception as e:
        console.print(f"[red]Failed to start '{label}': {e}[/red]")
        log_fd.write(f"\n[ERROR] Failed to start: {e}\n")
        log_fd.close()
        return None


def _stop_companion(name: str, pid: int, graceful_timeout: float = 5.0) -> bool:
    """Stop a companion process. Returns True if stopped."""
    if not _is_running(pid):
        return True

    try:
        # Send SIGTERM to process group
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return True

    # Wait for graceful shutdown
    deadline = time.time() + graceful_timeout
    while time.time() < deadline:
        if not _is_running(pid):
            return True
        time.sleep(0.2)

    # Force kill
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    time.sleep(0.3)
    return not _is_running(pid)


# --- Typer commands ---

@app.command()
def start(
    name: Optional[str] = typer.Argument(None, help="Companion name (omit to start all)"),
) -> None:
    """Start companion process(es)."""
    companions = _find_companion_config()
    if not companions:
        console.print("[red]No companion config found.[/red]")
        console.print("Create a [cyan]klight-companions.yaml[/cyan] or add a [cyan]companions:[/cyan] section to klight-team.yaml.")
        raise typer.Exit(1)

    pids = _load_pids()

    if name:
        # Start single companion
        if name not in companions:
            console.print(f"[red]Unknown companion: '{name}'[/red]")
            console.print(f"Available: {', '.join(companions.keys())}")
            raise typer.Exit(1)

        # Check if already running
        existing_pid = pids.get(name)
        if existing_pid and _is_running(existing_pid):
            label = companions[name].get("label", name)
            console.print(f"[yellow]{label} is already running (PID {existing_pid})[/yellow]")
            return

        config = companions[name]
        label = config.get("label", name)
        console.print(f"Starting [cyan]{label}[/cyan]...")
        pid = _start_companion(name, config)
        if pid:
            pids[name] = pid
            _save_pids(pids)
            console.print(f"  [green]✓[/green] {label} started (PID {pid})")
            port = config.get("port")
            if port:
                console.print(f"    → http://localhost:{port}")
        else:
            console.print(f"  [red]✗[/red] Failed to start {label}")
            raise typer.Exit(1)
    else:
        # Start all companions
        console.print(f"[bold]Starting {len(companions)} companion(s)...[/bold]\n")
        started = 0
        for comp_name, config in companions.items():
            label = config.get("label", comp_name)
            existing_pid = pids.get(comp_name)
            if existing_pid and _is_running(existing_pid):
                console.print(f"  [dim]⊘[/dim] {label} already running (PID {existing_pid})")
                started += 1
                continue

            pid = _start_companion(comp_name, config)
            if pid:
                pids[comp_name] = pid
                console.print(f"  [green]✓[/green] {label} (PID {pid})")
                port = config.get("port")
                if port:
                    console.print(f"    → http://localhost:{port}")
                started += 1
            else:
                console.print(f"  [red]✗[/red] {label} — failed to start")

        _save_pids(pids)
        console.print(f"\n[green]{started}/{len(companions)} companion(s) started.[/green]")


@app.command()
def stop(
    name: Optional[str] = typer.Argument(None, help="Companion name (omit to stop all)"),
) -> None:
    """Stop companion process(es)."""
    companions = _find_companion_config()
    pids = _load_pids()

    if name:
        # Stop single companion
        pid = pids.get(name)
        if not pid:
            console.print(f"[yellow]No running PID found for '{name}'.[/yellow]")
            return

        label = name
        if companions and name in companions:
            label = companions[name].get("label", name)

        console.print(f"Stopping [cyan]{label}[/cyan] (PID {pid})...")
        if _stop_companion(name, pid):
            del pids[name]
            _save_pids(pids)
            console.print(f"  [green]✓[/green] Stopped.")
        else:
            console.print(f"  [red]✗[/red] Failed to stop (PID {pid}). Try: kill -9 {pid}")
            raise typer.Exit(1)
    else:
        # Stop all
        if not pids:
            console.print("[yellow]No companion processes running.[/yellow]")
            return

        console.print(f"[bold]Stopping {len(pids)} companion(s)...[/bold]\n")
        stopped = 0
        for comp_name, pid in list(pids.items()):
            label = comp_name
            if companions and comp_name in companions:
                label = companions[comp_name].get("label", comp_name)

            if not _is_running(pid):
                console.print(f"  [dim]⊘[/dim] {label} already stopped")
                del pids[comp_name]
                stopped += 1
                continue

            if _stop_companion(comp_name, pid):
                console.print(f"  [green]✓[/green] {label} stopped")
                del pids[comp_name]
                stopped += 1
            else:
                console.print(f"  [red]✗[/red] {label} — failed to stop (PID {pid})")

        _save_pids(pids)
        console.print(f"\n[green]{stopped} companion(s) stopped.[/green]")


@app.command()
def restart(
    name: Optional[str] = typer.Argument(None, help="Companion name (omit to restart all)"),
) -> None:
    """Restart companion process(es)."""
    companions = _find_companion_config()
    if not companions:
        console.print("[red]No companion config found.[/red]")
        raise typer.Exit(1)

    pids = _load_pids()

    targets = [name] if name else list(companions.keys())

    for comp_name in targets:
        if comp_name not in companions:
            console.print(f"[red]Unknown companion: '{comp_name}'[/red]")
            continue

        config = companions[comp_name]
        label = config.get("label", comp_name)
        existing_pid = pids.get(comp_name)

        # Stop if running
        if existing_pid and _is_running(existing_pid):
            console.print(f"  Stopping [cyan]{label}[/cyan]...")
            _stop_companion(comp_name, existing_pid)
            if comp_name in pids:
                del pids[comp_name]
            time.sleep(0.5)

        # Start
        console.print(f"  Starting [cyan]{label}[/cyan]...")
        pid = _start_companion(comp_name, config)
        if pid:
            pids[comp_name] = pid
            console.print(f"  [green]✓[/green] {label} restarted (PID {pid})")
        else:
            console.print(f"  [red]✗[/red] {label} — failed to restart")

    _save_pids(pids)


@app.command(name="status")
def status_cmd() -> None:
    """Show status of all companion processes."""
    companions = _find_companion_config()
    if not companions:
        console.print("[yellow]No companion config found.[/yellow]")
        return

    pids = _load_pids()

    table = Table(title="Companion Processes")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Label", style="white")
    table.add_column("Status", justify="center")
    table.add_column("PID", justify="right")
    table.add_column("Port", justify="right")
    table.add_column("Port Active", justify="center")
    table.add_column("Node", justify="center")

    for comp_name, config in companions.items():
        label = config.get("label", comp_name)
        pid = pids.get(comp_name)
        port = config.get("port")
        node = config.get("node")

        if pid and _is_running(pid):
            status_str = "[green]● Running[/green]"
            pid_str = str(pid)
        elif pid:
            status_str = "[red]● Dead[/red]"
            pid_str = f"[dim]{pid}[/dim]"
        else:
            status_str = "[dim]○ Stopped[/dim]"
            pid_str = "-"

        port_str = str(port) if port else "-"
        port_active = ""
        if port:
            if _check_port(port):
                port_active = "[green]✓[/green]"
            elif pid and _is_running(pid):
                port_active = "[yellow]…[/yellow]"
            else:
                port_active = "[dim]-[/dim]"

        node_str = str(node) if node else "-"

        table.add_row(comp_name, label, status_str, pid_str, port_str, port_active, node_str)

    console.print(table)

    # Summary
    running_count = sum(1 for n in companions if pids.get(n) and _is_running(pids[n]))
    total = len(companions)
    if running_count == total:
        console.print(f"\n[green]All {total} companions running.[/green]")
    elif running_count > 0:
        console.print(f"\n[yellow]{running_count}/{total} companions running.[/yellow]")
    else:
        console.print(f"\n[dim]No companions running.[/dim]")


@app.command()
def logs(
    name: str = typer.Argument(..., help="Companion name"),
    follow: bool = typer.Option(False, "-f", "--follow", help="Follow log output"),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """View logs for a companion process."""
    companions = _find_companion_config()
    if companions and name not in companions:
        console.print(f"[red]Unknown companion: '{name}'[/red]")
        console.print(f"Available: {', '.join(companions.keys())}")
        raise typer.Exit(1)

    log_file = _get_log_file(name)
    if not log_file.exists():
        console.print(f"[yellow]No logs found for '{name}'.[/yellow]")
        console.print(f"[dim]Expected at: {log_file}[/dim]")
        raise typer.Exit(0)

    if follow:
        # Use tail -f for following
        label = name
        if companions and name in companions:
            label = companions[name].get("label", name)
        console.print(f"[dim]Following logs for {label} ({log_file})...[/dim]\n")
        try:
            proc = subprocess.run(
                ["tail", "-f", "-n", str(tail), str(log_file)],
            )
        except KeyboardInterrupt:
            pass
    else:
        # Read last N lines
        try:
            lines = log_file.read_text().splitlines()
            output_lines = lines[-tail:] if len(lines) > tail else lines
            for line in output_lines:
                console.print(line)
        except Exception as e:
            console.print(f"[red]Error reading logs: {e}[/red]")
            raise typer.Exit(1)
