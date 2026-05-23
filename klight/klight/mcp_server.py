"""
klight MCP server — exposes klight as tools for Claude / any MCP-compatible LLM.

Usage:
  klight mcp                          # start stdio server

Claude Desktop ~/.config/claude/claude_desktop_config.json:
  {
    "mcpServers": {
      "klight": {
        "command": "klight",
        "args": ["mcp"],
        "env": { "KUBECONFIG": "/tmp/klight-demo-kubeconfig.yaml" }
      }
    }
  }

Claude Code (CLI):
  claude mcp add klight -- klight mcp
"""

import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "klight",
    instructions="""
You manage Kubernetes development environments with klight.

klight gives every developer an isolated namespace (env-<name>) with services
and infrastructure (postgres, kafka, redis, etc.) auto-wired. No K8s YAML needed.

Three workflows:
- World 1 (local repos): deploy_from_repos — user has cloned service repos
- World 2 (team sync): deploy_environment — images from CI, synced via klight-team.yaml
- World 3 (remote cluster): same as World 2 but targeting a remote EKS/GKE cluster

Rules:
- Always ask for confirmation before calling destroy_environment
- For broken services, call get_unready first to get fix hints
- Use service_status to understand what's running before taking actions
- The cluster resource shows current context — never target production clusters
""",
)

_ENV = {**os.environ, "NO_COLOR": "1"}


def _klight(*args: str, timeout: int = 300) -> str:
    result = subprocess.run(
        ["klight"] + list(args),
        capture_output=True,
        text=True,
        env=_ENV,
        timeout=timeout,
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    if result.returncode != 0:
        return f"ERROR (exit {result.returncode}):\n{err or out}"
    return out or err or "(done)"


# ---------------------------------------------------------------------------
# Resources — context Claude reads automatically
# ---------------------------------------------------------------------------


@mcp.resource("klight://cluster")
def cluster_resource() -> str:
    """Current cluster target, CPUs, RAM, and minikube status."""
    target = _klight("target")
    status = _klight("local", "status")
    return f"=== Cluster Target ===\n{target}\n\n=== Local Cluster Status ===\n{status}"


@mcp.resource("klight://environments")
def environments_resource() -> str:
    """All active klight environments and their services."""
    result = subprocess.run(
        ["kubectl", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True, text=True, env=_ENV,
    )
    all_ns = result.stdout.split()
    env_ns = [ns for ns in all_ns if ns.startswith("env-")]
    if not env_ns:
        return "No active environments found."
    lines = ["Active environments:"]
    for ns in env_ns:
        env_name = ns.removeprefix("env-")
        ps_out = _klight("ps", "--env", env_name)
        lines.append(f"\n--- {env_name} ---\n{ps_out}")
    return "\n".join(lines)


@mcp.resource("klight://team-yaml")
def team_yaml_resource() -> str:
    """Current cached klight-team.yaml (synced via klight sync)."""
    cache_path = Path.home() / ".klight" / "team.yaml"
    if not cache_path.exists():
        return "No klight-team.yaml cached. Run: klight sync <url>"
    return cache_path.read_text()


# ---------------------------------------------------------------------------
# Tools — actions Claude can invoke
# ---------------------------------------------------------------------------


@mcp.tool()
def deploy_environment(profile: str, env_name: str, timeout: int = 300) -> str:
    """
    Deploy a profile to a named Kubernetes environment (World 2 / World 3).
    Uses images from CI as defined in the synced klight-team.yaml.
    Requires klight sync to have been run first.

    Args:
        profile: Profile name defined in klight-team.yaml (e.g. "store", "full")
        env_name: Environment name — becomes namespace env-<name> (e.g. "alice", "dev")
        timeout: Seconds to wait for all pods to become ready (default 300)
    """
    return _klight("up", profile, "--env", env_name, "--timeout", str(timeout), timeout=timeout + 30)


@mcp.tool()
def deploy_from_repos(repo_paths: list[str], env_name: str, timeout: int = 300) -> str:
    """
    Deploy services from local repository paths (World 1).
    Each repo must have a klight.yaml. Auto-generates K8s manifests and starts
    required infrastructure (postgres, kafka, etc.) in dependency order.

    Args:
        repo_paths: Absolute paths to service repos containing klight.yaml
        env_name: Environment name (e.g. "dev", "alice")
        timeout: Seconds to wait for all pods to become ready (default 300)
    """
    return _klight("from-repos", *repo_paths, "--env", env_name, "--timeout", str(timeout), timeout=timeout + 30)


@mcp.tool()
def service_status(env_name: str) -> str:
    """
    Show pod and service status for an environment as a formatted table.
    Displays service name, pod status, replica count, age, and image.

    Args:
        env_name: Environment name (e.g. "tienda", "dev", "alice")
    """
    return _klight("ps", "--env", env_name)


@mcp.tool()
def get_logs(service: str, env_name: str, tail: int = 100, since: str = "") -> str:
    """
    Get recent logs from a service in an environment.

    Args:
        service: Service name (e.g. "inventory-api", "store-web")
        env_name: Environment name
        tail: Number of recent lines to return (default 100)
        since: Return logs newer than this duration, e.g. "5m", "1h" (optional)
    """
    args = ["logs", service, "--env", env_name, "--tail", str(tail)]
    if since:
        args += ["--since", since]
    return _klight(*args)


@mcp.tool()
def destroy_environment(env_name: str) -> str:
    """
    Destroy an environment — deletes the namespace and all its resources.
    THIS IS DESTRUCTIVE AND IRREVERSIBLE. Always confirm with the user first.

    Args:
        env_name: Environment name to destroy (e.g. "alice", "dev")
    """
    return _klight("destroy", env_name, "--yes")


@mcp.tool()
def replace_service(service: str, env_name: str, path: str) -> str:
    """
    Replace a running service with a locally built image (hot-swap).
    Builds from the given path, loads into minikube, and restarts the pod.
    Other services keep their CI images.

    Args:
        service: Service name to replace (e.g. "store-api")
        env_name: Environment name
        path: Absolute path to the service repo with a Dockerfile
    """
    return _klight("replace", service, "--env", env_name, "--with", path, timeout=180)


@mcp.tool()
def restore_service(service: str, env_name: str) -> str:
    """
    Restore a service to its CI image, undoing a previous klight replace.

    Args:
        service: Service name to restore
        env_name: Environment name
    """
    return _klight("restore", service, "--env", env_name)


@mcp.tool()
def get_unready(env_name: str) -> str:
    """
    Show services that are not Ready in an environment, with a fix hint for each.
    Use this when something is broken to quickly understand the root cause.

    Args:
        env_name: Environment name
    """
    return _klight("unready", "--env", env_name)


@mcp.tool()
def init_service(repo_path: str) -> str:
    """
    Scan a service repository and auto-generate a klight.yaml file.
    Detects port, health endpoint, framework, and infrastructure dependencies.

    Args:
        repo_path: Absolute path to the service repo to scan
    """
    return _klight("init", repo_path, "--yes")


@mcp.tool()
def sync_team(url: str = "") -> str:
    """
    Download and cache the klight-team.yaml from a URL.
    After syncing, deploy_environment will use the updated service definitions.
    If url is empty, re-syncs from the previously used URL.

    Args:
        url: URL to klight-team.yaml (e.g. raw GitHub URL). Empty = re-sync.
    """
    args = ["sync"]
    if url:
        args.append(url)
    return _klight(*args)


@mcp.tool()
def switch_target(target: str) -> str:
    """
    Switch the active cluster target.

    Args:
        target: "local" for minikube klight-demo, "remote" or "klight-remote" for
                a configured remote cluster, or any kubectl context name
    """
    return _klight("use", target)


@mcp.tool()
def run_preflight(env_name: str = "", profile: str = "") -> str:
    """
    Check image availability before deploying. Reports missing images and
    whether they can be pulled or need to be built locally.

    Args:
        env_name: Environment name to check (optional)
        profile: Profile name to check (optional)
    """
    args = ["preflight"]
    if env_name:
        args += ["--env", env_name]
    if profile:
        args += ["--profile", profile]
    return _klight(*args)
