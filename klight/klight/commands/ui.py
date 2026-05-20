"""klight ui — starts the web dashboard."""
import subprocess
import webbrowser
import time
import typer
from rich.console import Console
from pathlib import Path

app = typer.Typer(help="Open the klight web dashboard.")
console = Console()

UI_PORT = 7700
UI_DIR = Path(__file__).parent.parent.parent.parent / "klight-ui"


@app.command()
def cmd(
    port: int = typer.Option(UI_PORT, "--port", "-p", help="Port to run the UI on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser automatically"),
) -> None:
    """Start the klight web dashboard."""
    server_path = UI_DIR / "server.py"
    if not server_path.exists():
        console.print(f"[red]UI server not found at {server_path}[/red]")
        raise typer.Exit(1)

    # Install fastapi/uvicorn if needed
    try:
        import fastapi  # noqa
        import uvicorn  # noqa
    except ImportError:
        console.print("Installing UI dependencies...")
        subprocess.run(
            ["pip", "install", "fastapi", "uvicorn", "--break-system-packages", "-q"],
            check=True,
        )

    url = f"http://localhost:{port}"
    console.print(f"[bold]klight UI[/bold] starting at [cyan]{url}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    if not no_browser:
        # Open browser after a short delay
        import threading
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    import sys
    import os
    sys.path.insert(0, str(UI_DIR))
    os.environ.setdefault("KLIGHT_MANIFESTS_DIR",
                          str(Path(__file__).parent.parent.parent.parent / "manifests"))

    import uvicorn as uv
    from server import app as ui_app
    uv.run(ui_app, host="127.0.0.1", port=port, log_level="error")
