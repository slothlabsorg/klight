"""
klight watch — hot reload: watches source files, rebuilds image, restarts pod.
Does NOT touch the user's code. Invokes their existing build process.
"""

import subprocess
import time
import threading
from pathlib import Path
import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text
from klight.schema import KlightConfig
from klight import kubectl as k

app = typer.Typer(help="Watch source files and rebuild/restart on changes.")
console = Console()


def _get_mtimes(paths: list[Path]) -> dict[str, float]:
    mtimes = {}
    for base in paths:
        if not base.exists():
            continue
        if base.is_file():
            mtimes[str(base)] = base.stat().st_mtime
        else:
            for f in base.rglob("*"):
                if f.is_file() and not any(
                    part.startswith(".") or part in ("build", "target", "__pycache__", "node_modules", ".gradle")
                    for part in f.parts
                ):
                    mtimes[str(f)] = f.stat().st_mtime
    return mtimes


def _build_image(cfg: KlightConfig, repo_path: Path) -> bool:
    """Build the Docker image using the service's build config or Dockerfile."""
    image = cfg.effective_image()

    if cfg.build and cfg.build.command:
        cmd = cfg.build.command
        cwd = (repo_path / cfg.build.context).resolve()
        console.print(f"  [dim]$ {cmd}[/dim]")
        result = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
    else:
        # Standard Dockerfile build
        cmd = f"docker build -t {image} ."
        console.print(f"  [dim]$ {cmd}[/dim]")
        result = subprocess.run(
            ["docker", "build", "-t", image, str(repo_path)],
            capture_output=True, text=True,
        )

    if result.returncode != 0:
        console.print(f"  [red]Build failed:[/red]")
        console.print(result.stderr[-2000:] if result.stderr else "(no output)")
        return False
    return True


def _load_to_minikube(image: str, profile: str = "klight-demo") -> bool:
    result = subprocess.run(
        ["minikube", "image", "load", image, f"--profile={profile}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _restart_pod(service_name: str, namespace: str) -> bool:
    result = k.run(["rollout", "restart", f"deployment/{service_name}", "-n", namespace])
    return result.returncode == 0


def _is_local_target() -> bool:
    import subprocess as sp
    r = sp.run(["kubectl", "config", "current-context"], capture_output=True, text=True)
    ctx = r.stdout.strip()
    return ctx in ("klight-demo", "minikube") or "minikube" in ctx


def _run_cycle(
    cfg: KlightConfig,
    repo_path: Path,
    namespace: str,
    minikube_profile: str,
    label: str = "",
) -> bool:
    """Build → load → restart. Returns True on success."""
    ts = time.strftime("%H:%M:%S")
    tag = f"[{ts}]{f' [{label}]' if label else ''}"

    console.print(f"{tag} Building {cfg.effective_image()}...")
    t_start = time.time()

    if not _build_image(cfg, repo_path):
        console.print(f"{tag} [red]Build failed — will retry on next change[/red]")
        return False

    is_local = _is_local_target()
    if is_local:
        console.print(f"{tag} Loading into minikube ({minikube_profile})...")
        if not _load_to_minikube(cfg.effective_image(), minikube_profile):
            console.print(f"{tag} [red]minikube image load failed[/red]")
            return False
    else:
        console.print(f"{tag} [dim]Remote cluster — skipping minikube load[/dim]")

    console.print(f"{tag} Restarting {cfg.name} in {namespace}...")
    _restart_pod(cfg.name, namespace)

    elapsed = round(time.time() - t_start)
    console.print(f"{tag} [green]✓ Done[/green] in {elapsed}s — {cfg.name} redeployed\n")
    return True


def _watch_loop(
    cfg: KlightConfig,
    repo_path: Path,
    namespace: str,
    watch_paths: list[Path],
    minikube_profile: str,
    stop_event: threading.Event,
) -> None:
    console.print(f"  Watching: {[str(p) for p in watch_paths]}")
    console.print(f"  [dim]Ctrl+C to stop[/dim]\n")

    last_mtimes = _get_mtimes(watch_paths)

    while not stop_event.is_set():
        time.sleep(2)
        current_mtimes = _get_mtimes(watch_paths)

        changed = {f for f, mt in current_mtimes.items() if last_mtimes.get(f) != mt}
        changed |= {f for f in last_mtimes if f not in current_mtimes}

        if not changed:
            continue

        last_mtimes = current_mtimes
        changed_display = ", ".join(Path(f).name for f in list(changed)[:3])
        if len(changed) > 3:
            changed_display += f" (+{len(changed)-3} more)"

        ts = time.strftime("%H:%M:%S")
        console.print(f"[{ts}] [yellow]Change detected:[/yellow] {changed_display}")
        _run_cycle(cfg, repo_path, namespace, minikube_profile)


@app.command()
def cmd(
    service: str = typer.Argument(..., help="Service name (must match klight.yaml name)"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    path: Path = typer.Option(None, "--path", help="Path to service repo (default: ./<service>)"),
    profile: str = typer.Option("klight-demo", "--profile", help="minikube profile name"),
    initial_build: bool = typer.Option(
        True,
        "--initial-build/--no-initial-build",
        help="Build and reload the service once on startup before watching.",
    ),
) -> None:
    """
    Watch a service's source files and rebuild + restart the pod on every change.
    Does NOT touch your code — uses your existing Dockerfile or build command.

    Builds once immediately on startup (use --no-initial-build to skip).

    Example:
      klight watch store-api --env alice --path ./store-api
    """
    repo_path = (path or Path(f"./{service}")).resolve()
    klf = repo_path / "klight.yaml"

    if not klf.exists():
        console.print(f"[red]No klight.yaml in {repo_path}[/red]")
        raise typer.Exit(1)

    cfg = KlightConfig.from_file(klf)
    ns = f"env-{env_name}"

    # Determine what paths to watch
    if cfg.watch_paths:
        watch_paths = [repo_path / p for p in cfg.watch_paths]
    else:
        watch_paths = [repo_path / "src", repo_path / "app", repo_path / "lib"]
        watch_paths = [p for p in watch_paths if p.exists()] or [repo_path]

    console.print(f"[bold]klight watch[/bold] — {cfg.name} → {ns}")
    console.print(f"  Image:    {cfg.effective_image()}")
    console.print(f"  Cluster:  {profile}")

    if initial_build:
        console.print(f"\n[bold]Initial build[/bold] (--no-initial-build to skip)...")
        _run_cycle(cfg, repo_path, ns, profile)

    stop = threading.Event()
    thread = threading.Thread(
        target=_watch_loop,
        args=(cfg, repo_path, ns, watch_paths, profile, stop),
        daemon=True,
    )
    thread.start()

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopping watch...[/dim]")
        stop.set()
