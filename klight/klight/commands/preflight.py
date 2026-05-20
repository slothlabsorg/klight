"""
klight preflight — checks what images are missing before deploying.
Run before 'klight from-repos' to know exactly what needs to be built/pulled.
"""

import subprocess
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich import box
from klight.schema import KlightConfig
from klight import catalog as cat

app = typer.Typer(help="Check image availability before deploying.")
console = Console()


def _images_in_minikube(profile: str = "klight-demo") -> set[str]:
    result = subprocess.run(
        ["minikube", "image", "ls", f"--profile={profile}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    lines = result.stdout.strip().split("\n")
    # Strip docker.io/library/ prefix for matching
    images = set()
    for line in lines:
        name = line.strip().replace("docker.io/library/", "").replace("docker.io/", "")
        images.add(name)
    return images


def _image_in_docker(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    return result.returncode == 0


@app.command()
def cmd(
    repos: list[Path] = typer.Argument(None, help="Service repo paths (optional)"),
    env_name: str = typer.Option("", "--env", help="Environment name (for context)"),
    fix: bool = typer.Option(False, "--fix", help="Build/pull all missing images automatically"),
    profile: str = typer.Option("klight-demo", "--profile", help="minikube profile"),
) -> None:
    """
    Check that all required images are available in minikube before deploying.
    Shows exactly what needs to be built or pulled.

    Example:
      klight preflight services/store-api services/billing-service --env alice
      klight preflight services/store-api --fix
    """
    in_minikube = _images_in_minikube(profile)
    missing: list[tuple[str, str, str]] = []  # (image, type, fix_cmd)

    table = Table(title="Preflight Check", box=box.ROUNDED)
    table.add_column("Image", style="cyan", min_width=30)
    table.add_column("Type", min_width=10)
    table.add_column("Status", min_width=14)
    table.add_column("Fix")

    def check(image: str, kind: str, fix_cmd: str) -> None:
        in_mk = any(image in img or img in image for img in in_minikube)
        if in_mk:
            table.add_row(image, kind, "[green]✓ ready[/green]", "")
        else:
            table.add_row(image, kind, "[red]✗ missing[/red]", fix_cmd)
            missing.append((image, kind, fix_cmd))

    # Sentinel
    check("klight-sentinel:latest", "klight",
          "cd sentinel && docker build -t klight-sentinel:latest . && minikube image load klight-sentinel:latest")

    # Service images from repos
    configs: list[KlightConfig] = []
    if repos:
        for repo_path in repos:
            klf = repo_path.resolve() / "klight.yaml"
            if klf.exists():
                cfg = KlightConfig.from_file(klf)
                configs.append(cfg)
                check(
                    cfg.effective_image(),
                    "service",
                    f"klight local build-load {cfg.name} --path {repo_path}",
                )

    # Infra images needed by all services
    all_infra: set[str] = set()
    for cfg in configs:
        all_infra.update(n.name for n in cfg.local_needs())

    for infra_name in sorted(all_infra):
        img = cat.image(infra_name)
        check(
            img,
            f"infra/{infra_name}",
            f"docker pull {img} && minikube image load {img} --profile {profile}",
        )

    console.print(table)

    if not missing:
        console.print("\n[bold green]All images ready![/bold green] Safe to deploy.")
        return

    console.print(f"\n[yellow]{len(missing)} image(s) missing.[/yellow]")

    if fix:
        console.print("\n[bold]Running fixes...[/bold]")
        for image, kind, fix_cmd in missing:
            console.print(f"\n  [dim]$ {fix_cmd}[/dim]")
            result = subprocess.run(fix_cmd, shell=True, capture_output=False)
            if result.returncode != 0:
                console.print(f"  [red]Failed: {image}[/red]")
            else:
                console.print(f"  [green]✓ {image}[/green]")
    else:
        console.print("\nFix commands:")
        for _, _, fix_cmd in missing:
            console.print(f"  [dim]{fix_cmd}[/dim]")
        console.print(f"\nOr run: [cyan]klight preflight --fix[/cyan]")
        raise typer.Exit(1)
