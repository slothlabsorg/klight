import subprocess
import time
import webbrowser
import typer
from rich.console import Console
from klight import kubectl as k

app = typer.Typer(help="Port-forward a service and open it in the browser.")
console = Console()


@app.command()
def cmd(
    service: str = typer.Argument(..., help="Service name"),
    env_name: str = typer.Option(..., "--env", help="Environment name"),
    port: int = typer.Option(None, "--port", help="Local port (auto-detects from service if not set)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Only port-forward, don't open browser (for CI)"),
) -> None:
    """Port-forward a service to localhost and open it in the browser."""
    ns = f"env-{env_name}"

    # Auto-detect service port if not provided
    target_port = port
    if target_port is None:
        svc_data = k.run_json(["get", "service", service, "-n", ns])
        if svc_data:
            ports = svc_data.get("spec", {}).get("ports", [])
            if ports:
                target_port = ports[0].get("port", 8080)
        if target_port is None:
            target_port = 8080
            console.print(f"[yellow]Could not detect port, defaulting to {target_port}[/yellow]")

    local_port = target_port
    url = f"http://localhost:{local_port}"

    console.print(f"[green]Port-forwarding[/green] {service}:{target_port} → localhost:{local_port}")
    console.print(f"  [dim]Press Ctrl+C to stop[/dim]")

    # Start port-forward in background
    pf_proc = subprocess.Popen(
        ["kubectl", "port-forward", f"svc/{service}", f"{local_port}:{target_port}", "-n", ns],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait a moment for port-forward to establish
    time.sleep(1.5)

    if pf_proc.poll() is not None:
        console.print(f"[red]Port-forward failed. Check: kubectl -n {ns} get svc {service}[/red]")
        raise typer.Exit(1)

    if not no_browser:
        console.print(f"[green]Opening[/green] {url}")
        webbrowser.open(url)

    console.print(f"\n[dim]{url}[/dim]")

    try:
        pf_proc.wait()
    except KeyboardInterrupt:
        pf_proc.terminate()
        console.print("\n[dim]Port-forward stopped.[/dim]")
