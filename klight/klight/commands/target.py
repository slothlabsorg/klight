"""
klight use — switch between local and remote cluster targets.
klight target — show current target.
klight connect — configure remote cluster access.
"""

import subprocess
from pathlib import Path
import typer
from rich.console import Console
from klight import config as cfg

app = typer.Typer(help="Manage local/remote cluster targets.")
console = Console()


@app.command(name="use")
def use_target(
    target: str = typer.Argument(..., help="Target name: 'local', 'remote', or a kubectl context name"),
) -> None:
    """
    Switch to a cluster target.

      klight use local      → minikube klight-demo
      klight use remote     → company's dev cluster
      klight use my-context → any kubectl context by name
    """
    resolved = cfg.context_for(target) or target
    result = subprocess.run(
        ["kubectl", "config", "use-context", resolved],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Context not found:[/red] {resolved}")
        console.print("Available contexts:")
        subprocess.run(["kubectl", "config", "get-contexts", "--no-headers", "-o", "name"])
        raise typer.Exit(1)

    is_local = (resolved == cfg.context_for("local") or resolved == "klight-demo")
    label = "🖥  local (minikube)" if is_local else "☁  remote"
    console.print(f"[green]✓[/green] Switched to {label}: [cyan]{resolved}[/cyan]")
    console.print(f"  klight up <profile> --env <name>")


@app.command(name="target")
def show_target() -> None:
    """Show current cluster target (local or remote)."""
    c = cfg.load()
    result = subprocess.run(
        ["kubectl", "config", "current-context"], capture_output=True, text=True
    )
    current = result.stdout.strip()
    local_ctx = c["targets"].get("local", "klight-demo")
    remote_ctx = c["targets"].get("remote", "")

    if current == local_ctx:
        console.print(f"[cyan]Target:[/cyan] [bold]local[/bold] ({current})")
        console.print(f"  Switch to remote: [dim]klight use remote[/dim]")
    elif remote_ctx and current == remote_ctx:
        console.print(f"[cyan]Target:[/cyan] [bold]remote[/bold] ({current})")
        console.print(f"  Switch to local:  [dim]klight use local[/dim]")
    else:
        console.print(f"[cyan]Target:[/cyan] [bold]{current}[/bold] (custom context)")

    configured = {}
    if local_ctx:
        configured["local"] = local_ctx
    if remote_ctx:
        configured["remote"] = remote_ctx
    if configured:
        console.print(f"\n  Configured targets:")
        for name, ctx in configured.items():
            marker = " ←" if ctx == current else ""
            console.print(f"    {name:<8} {ctx}{marker}")


@app.command(name="connect")
def connect(
    url: str = typer.Option("", "--url", help="Cluster API server URL"),
    token: str = typer.Option("", "--token", help="Bearer token for authentication"),
    kubeconfig: Path = typer.Option(None, "--kubeconfig", help="Path to kubeconfig file to import"),
    context_name: str = typer.Option("klight-remote", "--name", help="Name for the new context"),
) -> None:
    """
    Configure access to a remote cluster.

    Examples:
      klight connect --kubeconfig ~/Downloads/dev-cluster.yaml
      klight connect --url https://k8s.company.com --token eyJ...
    """
    if kubeconfig:
        # Import kubeconfig and add as a named context
        result = subprocess.run(
            ["kubectl", "config", "merge", str(kubeconfig)],
            capture_output=True, text=True,
        )
        # kubectl doesn't have merge — use KUBECONFIG env var trick
        import os
        existing = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config"))
        merged_env = f"{existing}:{kubeconfig}"
        r = subprocess.run(
            ["kubectl", "config", "view", "--flatten"],
            capture_output=True, text=True,
            env={**os.environ, "KUBECONFIG": merged_env},
        )
        if r.returncode == 0:
            kube_dir = Path.home() / ".kube"
            kube_dir.mkdir(exist_ok=True)
            (kube_dir / "config").write_text(r.stdout)
            console.print(f"[green]✓[/green] Kubeconfig merged from {kubeconfig}")
        else:
            console.print(f"[red]Failed to merge kubeconfig:[/red] {r.stderr}")
            raise typer.Exit(1)

    elif url and token:
        # Create cluster + credentials + context from token
        cmds = [
            ["kubectl", "config", "set-cluster", context_name, f"--server={url}", "--insecure-skip-tls-verify=true"],
            ["kubectl", "config", "set-credentials", f"{context_name}-user", f"--token={token}"],
            ["kubectl", "config", "set-context", context_name,
             f"--cluster={context_name}", f"--user={context_name}-user"],
        ]
        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                console.print(f"[red]Error:[/red] {r.stderr}")
                raise typer.Exit(1)
        console.print(f"[green]✓[/green] Context '{context_name}' configured → {url}")
        console.print(f"  Switch to it: [cyan]klight use {context_name}[/cyan]")

    else:
        c = cfg.load()
        remote_url = c.get("remote", {}).get("api_url", "")
        if remote_url:
            console.print(f"Remote cluster from klight.toml: [cyan]{remote_url}[/cyan]")
            console.print(f"Run: klight connect --url {remote_url} --token <your-token>")
        else:
            console.print("Usage:")
            console.print("  klight connect --kubeconfig ~/path/to/kubeconfig.yaml")
            console.print("  klight connect --url https://k8s.company.com --token <token>")


@app.command(name="setup-remote")
def setup_remote() -> None:
    """
    Configure the current cluster for klight remote access (run as DevOps admin).

    Creates klight-system namespace, klight-dev ServiceAccount with minimal RBAC,
    and generates a long-lived token. Share the printed command with your devs.
    """
    import base64, time

    def kubectl_apply(manifest: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=manifest, capture_output=True, text=True,
        )

    console.print("[bold]Setting up klight remote access on current cluster...[/bold]\n")

    r = kubectl_apply("""apiVersion: v1
kind: Namespace
metadata:
  name: klight-system
""")
    if r.returncode != 0:
        console.print(f"[red]Failed to create namespace:[/red] {r.stderr}")
        raise typer.Exit(1)
    console.print("[green]✓[/green] Namespace klight-system")

    kubectl_apply("""apiVersion: v1
kind: ServiceAccount
metadata:
  name: klight-dev
  namespace: klight-system
""")
    console.print("[green]✓[/green] ServiceAccount klight-dev")

    kubectl_apply("""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: klight-dev
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list", "watch", "create", "delete"]
- apiGroups: ["", "apps", "batch"]
  resources: ["*"]
  verbs: ["*"]
""")
    console.print("[green]✓[/green] ClusterRole klight-dev")

    kubectl_apply("""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: klight-dev
subjects:
- kind: ServiceAccount
  name: klight-dev
  namespace: klight-system
roleRef:
  kind: ClusterRole
  name: klight-dev
  apiGroup: rbac.authorization.k8s.io
""")
    console.print("[green]✓[/green] ClusterRoleBinding klight-dev\n")

    # Generate token — kubectl create token (K8s 1.24+)
    r = subprocess.run(
        ["kubectl", "create", "token", "klight-dev",
         "-n", "klight-system", "--duration=8760h"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        token = r.stdout.strip()
    else:
        # Fallback: Secret-based token for older clusters
        console.print("[dim]kubectl create token not available — using Secret token...[/dim]")
        kubectl_apply("""apiVersion: v1
kind: Secret
metadata:
  name: klight-dev-token
  namespace: klight-system
  annotations:
    kubernetes.io/service-account.name: klight-dev
type: kubernetes.io/service-account-token
""")
        time.sleep(3)
        r2 = subprocess.run(
            ["kubectl", "get", "secret", "klight-dev-token",
             "-n", "klight-system", "-o", "jsonpath={.data.token}"],
            capture_output=True, text=True,
        )
        if r2.returncode != 0 or not r2.stdout:
            console.print("[red]Failed to generate token[/red]")
            raise typer.Exit(1)
        token = base64.b64decode(r2.stdout).decode()

    r_url = subprocess.run(
        ["kubectl", "config", "view", "--minify",
         "-o", "jsonpath={.clusters[0].cluster.server}"],
        capture_output=True, text=True,
    )
    cluster_url = r_url.stdout.strip() or "https://YOUR-CLUSTER-URL"

    console.print("[bold green]Remote access configured.[/bold green]\n")
    console.print(f"Token (valid 1 year): [dim]{token[:30]}…[/dim]\n")
    console.print("[bold]Share with your devs:[/bold]")
    console.print(f"[cyan]  klight connect --url {cluster_url} --token {token}[/cyan]\n")
    console.print("[dim]After connecting:[/dim]")
    console.print("[dim]  klight use klight-remote[/dim]")
    console.print("[dim]  klight up store --env alice[/dim]")
