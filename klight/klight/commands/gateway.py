"""
klight gateway — Declarative gateway proxy for local development.

Reads gateway config from klight-team.yaml or klight-gateway.yaml,
spawns a lightweight HTTP proxy that routes by prefix:
  - Local services via port-forward targets
  - Remote passthrough to a shared dev API
  - Static mock responses for specified paths
  - Token swap (inject auth token for specified routes)

Usage:
  klight gateway start
  klight gateway stop
  klight gateway status
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import yaml
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Declarative gateway proxy for local development.")
console = Console()

_KLIGHT_DIR = Path.home() / ".klight"
_PID_FILE = _KLIGHT_DIR / "gateway.pid"

# ANSI color codes for request logging
_COLORS = {
    "local": "\033[32m",    # green
    "remote": "\033[34m",   # blue
    "mock": "\033[33m",     # yellow
    "swap": "\033[35m",     # magenta
    "reset": "\033[0m",
}


# --- Config loading ---

def _find_gateway_config() -> dict | None:
    """Search for gateway config in klight-gateway.yaml or klight-team.yaml."""
    search_paths = [
        Path.cwd() / "klight-gateway.yaml",
        Path.cwd() / "klight-team.yaml",
        _KLIGHT_DIR / "teams" / "klight-team.yaml",
    ]

    # Also check env var for team config
    env_path = os.environ.get("KLIGHT_GATEWAY_CONFIG")
    if env_path:
        search_paths.insert(0, Path(env_path).expanduser())

    for p in search_paths:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text())
                if data and "gateway" in data:
                    return data["gateway"]
            except Exception:
                continue

    return None


def _load_token(auth_config: dict) -> str | None:
    """Load bearer token from file or env var."""
    # Try env var first
    env_var = auth_config.get("remote_token_env", "DEVNEXT_BEARER_TOKEN")
    token = os.environ.get(env_var)
    if token:
        return token.strip()

    # Try file
    token_file = auth_config.get("remote_token_file", "~/.devnext-token")
    token_path = Path(token_file).expanduser()
    if token_path.exists():
        try:
            return token_path.read_text().strip()
        except Exception:
            pass

    return None


# --- Proxy Handler ---

class GatewayHandler(BaseHTTPRequestHandler):
    """HTTP request handler that routes based on gateway config."""

    gateway_config: dict = {}
    _token_cache: str | None = None
    _token_loaded: bool = False

    def log_message(self, format: str, *args) -> None:
        """Suppress default logging — we do our own colored logging."""
        pass

    def _log_request(self, route_type: str, method: str, path: str, status: int) -> None:
        color = _COLORS.get(route_type, "")
        reset = _COLORS["reset"]
        tag = f"[{route_type.upper():6s}]"
        print(f"{color}{tag}{reset} {method} {path} → {status}")

    def _get_token(self) -> str | None:
        if not GatewayHandler._token_loaded:
            auth_config = self.gateway_config.get("auth", {})
            GatewayHandler._token_cache = _load_token(auth_config)
            GatewayHandler._token_loaded = True
        return GatewayHandler._token_cache

    def _should_swap_token(self, path: str) -> bool:
        auth_config = self.gateway_config.get("auth", {})
        swap_routes = auth_config.get("swap_routes", [])
        for prefix in swap_routes:
            if path.startswith(prefix):
                return True
        return False

    def _find_mock(self, path: str) -> dict | None:
        mocks = self.gateway_config.get("mocks", [])
        for mock in mocks:
            if path == mock.get("path") or path.startswith(mock.get("path", "\x00") + "/"):
                return mock
        return None

    def _find_local_route(self, path: str) -> dict | None:
        routes = self.gateway_config.get("routes", [])
        for route in routes:
            prefix = route.get("prefix", "")
            if path.startswith(prefix):
                return route
        return None

    def _add_cors_headers(self, headers: dict | None = None) -> dict:
        """Build CORS headers."""
        cors_headers = {}
        if self.gateway_config.get("cors", True):
            cors_headers["Access-Control-Allow-Origin"] = "*"
            cors_headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            cors_headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin"
            cors_headers["Access-Control-Max-Age"] = "86400"
        if headers:
            cors_headers.update(headers)
        return cors_headers

    def _send_response_data(self, status: int, body: bytes, content_type: str = "application/json",
                            extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in self._add_cors_headers(extra_headers).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _serve_mock(self, mock: dict, method: str, path: str) -> None:
        """Serve a static mock file."""
        mock_file = mock.get("file", "")
        # Resolve relative to CWD
        mock_path = Path.cwd() / mock_file
        if not mock_path.exists():
            # Try relative to config location
            mock_path = _KLIGHT_DIR / "teams" / mock_file
        if mock_path.exists():
            try:
                body = mock_path.read_bytes()
                self._send_response_data(200, body)
                self._log_request("mock", method, path, 200)
                return
            except Exception as e:
                err = json.dumps({"error": f"Failed to read mock: {e}"}).encode()
                self._send_response_data(500, err)
                self._log_request("mock", method, path, 500)
                return

        err = json.dumps({"error": f"Mock file not found: {mock_file}"}).encode()
        self._send_response_data(404, err)
        self._log_request("mock", method, path, 404)

    def _proxy_to_local(self, route: dict, method: str, path: str, body: bytes | None) -> None:
        """Proxy request to a local service."""
        target = route.get("target", "localhost:8080")
        if not target.startswith("http"):
            target = f"http://{target}"
        url = f"{target}{path}"
        self._do_proxy(url, method, path, body, "local", inject_token=False)

    def _proxy_to_remote(self, method: str, path: str, body: bytes | None) -> None:
        """Proxy request to the remote API."""
        remote_base = self.gateway_config.get("remote", "")
        if not remote_base:
            err = json.dumps({"error": "No remote configured"}).encode()
            self._send_response_data(502, err)
            self._log_request("remote", method, path, 502)
            return

        url = f"{remote_base.rstrip('/')}{path}"
        inject_token = self._should_swap_token(path)
        route_type = "swap" if inject_token else "remote"
        self._do_proxy(url, method, path, body, route_type, inject_token=inject_token)

    def _do_proxy(self, url: str, method: str, path: str, body: bytes | None,
                  route_type: str, inject_token: bool = False) -> None:
        """Perform the actual HTTP proxy request."""
        # Build headers — forward most original headers
        headers = {}
        for key in self.headers:
            lower = key.lower()
            if lower in ("host", "connection", "transfer-encoding"):
                continue
            headers[key] = self.headers[key]

        # Token swap
        if inject_token:
            token = self._get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        try:
            req = Request(url, data=body, headers=headers, method=method)
            with urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                status = resp.status
                content_type = resp.getheader("Content-Type", "application/octet-stream")
                self._send_response_data(status, resp_body, content_type)
                self._log_request(route_type, method, path, status)
        except HTTPError as e:
            resp_body = e.read() if e.fp else b""
            content_type = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            self._send_response_data(e.code, resp_body, content_type)
            self._log_request(route_type, method, path, e.code)
        except URLError as e:
            err = json.dumps({"error": f"Proxy error: {e.reason}"}).encode()
            self._send_response_data(502, err)
            self._log_request(route_type, method, path, 502)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode()
            self._send_response_data(502, err)
            self._log_request(route_type, method, path, 502)

    def _read_body(self) -> bytes | None:
        content_length = self.headers.get("Content-Length")
        if content_length:
            return self.rfile.read(int(content_length))
        return None

    def _route_request(self, method: str) -> None:
        """Main routing logic."""
        path = self.path

        # 1. Check mocks first (exact match priority)
        mock = self._find_mock(path)
        if mock:
            self._serve_mock(mock, method, path)
            return

        # 2. Check local routes
        route = self._find_local_route(path)
        if route:
            body = self._read_body()
            self._proxy_to_local(route, method, path, body)
            return

        # 3. Fall through to remote
        body = self._read_body()
        self._proxy_to_remote(method, path, body)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(204)
        for k, v in self._add_cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self._log_request("local", "OPTIONS", self.path, 204)

    def do_GET(self) -> None:
        self._route_request("GET")

    def do_POST(self) -> None:
        self._route_request("POST")

    def do_PUT(self) -> None:
        self._route_request("PUT")

    def do_PATCH(self) -> None:
        self._route_request("PATCH")

    def do_DELETE(self) -> None:
        self._route_request("DELETE")

    def do_HEAD(self) -> None:
        self._route_request("HEAD")


# --- Server management ---

def _write_pid(pid: int) -> None:
    _KLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _read_pid() -> int | None:
    if _PID_FILE.exists():
        try:
            return int(_PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


def _clear_pid() -> None:
    if _PID_FILE.exists():
        _PID_FILE.unlink(missing_ok=True)


def _is_running(pid: int) -> bool:
    """Check if a process is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _run_server(config: dict, foreground: bool = False) -> None:
    """Start the gateway HTTP server."""
    port = config.get("port", 4300)
    GatewayHandler.gateway_config = config
    GatewayHandler._token_loaded = False
    GatewayHandler._token_cache = None

    server = HTTPServer(("0.0.0.0", port), GatewayHandler)

    def _shutdown(signum, frame):
        console.print("\n[yellow]Gateway shutting down...[/yellow]")
        server.shutdown()
        _clear_pid()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _write_pid(os.getpid())

    # Print startup info
    console.print(f"\n[bold green]⚡ klight gateway[/bold green] running on [cyan]http://localhost:{port}[/cyan]\n")
    remote = config.get("remote", "")
    if remote:
        console.print(f"  Remote: [blue]{remote}[/blue]")

    routes = config.get("routes", [])
    if routes:
        console.print("  [green]Local routes:[/green]")
        for r in routes:
            console.print(f"    {r['prefix']} → {r['target']}")

    mocks = config.get("mocks", [])
    if mocks:
        console.print(f"  [yellow]Mocks:[/yellow] {len(mocks)} path(s)")

    auth = config.get("auth", {})
    swap_routes = auth.get("swap_routes", [])
    if swap_routes:
        console.print(f"  [magenta]Token swap:[/magenta] {', '.join(swap_routes)}")

    console.print(f"\n  CORS: {'[green]enabled[/green]' if config.get('cors', True) else '[red]disabled[/red]'}")
    console.print("")

    server.serve_forever()


# --- Typer commands ---

@app.command()
def start(
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Override gateway port"),
    foreground: bool = typer.Option(True, "--foreground/--background", "-f/-b",
                                    help="Run in foreground (default) or background"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c",
                                               help="Path to gateway config file"),
) -> None:
    """Start the gateway proxy server."""
    # Check if already running
    pid = _read_pid()
    if pid and _is_running(pid):
        console.print(f"[yellow]Gateway already running (PID {pid}). Use 'klight gateway stop' first.[/yellow]")
        raise typer.Exit(1)

    # Load config
    if config_file:
        try:
            data = yaml.safe_load(config_file.read_text())
            config = data.get("gateway", data) if "gateway" in (data or {}) else data
        except Exception as e:
            console.print(f"[red]Failed to read config: {e}[/red]")
            raise typer.Exit(1)
    else:
        config = _find_gateway_config()

    if not config:
        console.print("[red]No gateway config found.[/red]")
        console.print("Create a [cyan]klight-gateway.yaml[/cyan] or add a [cyan]gateway:[/cyan] section to klight-team.yaml.")
        console.print("\nExample:")
        console.print("""[dim]
gateway:
  port: 4300
  remote: https://api.dev.example.com
  cors: true
  routes:
    - prefix: /my-service
      target: localhost:8080
[/dim]""")
        raise typer.Exit(1)

    # Apply port override
    if port:
        config["port"] = port

    if foreground:
        _run_server(config, foreground=True)
    else:
        # Background mode: fork the process
        pid = os.fork()
        if pid == 0:
            # Child process
            os.setsid()
            # Redirect stdout/stderr to log file
            log_file = _KLIGHT_DIR / "gateway.log"
            log_fd = open(log_file, "a")
            os.dup2(log_fd.fileno(), sys.stdout.fileno())
            os.dup2(log_fd.fileno(), sys.stderr.fileno())
            _run_server(config, foreground=False)
        else:
            # Parent process
            time.sleep(0.5)
            if _is_running(pid):
                console.print(f"[green]Gateway started in background (PID {pid})[/green]")
                console.print(f"  Listening on port {config.get('port', 4300)}")
                console.print(f"  Logs: {_KLIGHT_DIR / 'gateway.log'}")
            else:
                console.print("[red]Gateway failed to start. Check logs.[/red]")
                raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop the gateway proxy server."""
    pid = _read_pid()
    if not pid:
        console.print("[yellow]No gateway PID file found. Gateway may not be running.[/yellow]")
        raise typer.Exit(0)

    if not _is_running(pid):
        console.print("[yellow]Gateway process not found (stale PID). Cleaning up.[/yellow]")
        _clear_pid()
        raise typer.Exit(0)

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to exit
        for _ in range(10):
            time.sleep(0.2)
            if not _is_running(pid):
                break
        else:
            # Force kill
            os.kill(pid, signal.SIGKILL)

        _clear_pid()
        console.print(f"[green]Gateway stopped (PID {pid}).[/green]")
    except ProcessLookupError:
        _clear_pid()
        console.print("[yellow]Gateway process already exited.[/yellow]")
    except PermissionError:
        console.print(f"[red]Permission denied stopping PID {pid}.[/red]")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show gateway status and configuration."""
    pid = _read_pid()
    running = pid is not None and _is_running(pid)

    table = Table(title="Gateway Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    table.add_row("Status", "[green]Running[/green]" if running else "[red]Stopped[/red]")
    if pid:
        table.add_row("PID", str(pid))

    config = _find_gateway_config()
    if config:
        table.add_row("Port", str(config.get("port", 4300)))
        table.add_row("Remote", config.get("remote", "(none)"))
        table.add_row("CORS", "enabled" if config.get("cors", True) else "disabled")

        routes = config.get("routes", [])
        if routes:
            route_str = "\n".join(f"{r['prefix']} → {r['target']}" for r in routes)
            table.add_row("Local Routes", route_str)

        mocks = config.get("mocks", [])
        if mocks:
            mock_str = "\n".join(m["path"] for m in mocks)
            table.add_row("Mocks", mock_str)

        auth = config.get("auth", {})
        swap_routes = auth.get("swap_routes", [])
        if swap_routes:
            table.add_row("Token Swap", ", ".join(swap_routes))

        token = _load_token(auth)
        table.add_row("Token Loaded", "[green]Yes[/green]" if token else "[red]No[/red]")
    else:
        table.add_row("Config", "[red]Not found[/red]")

    console.print(table)
