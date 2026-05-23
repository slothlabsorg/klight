"""
klight MCP server — exposes klight as tools for Claude / any MCP-compatible LLM.

Philosophy: the MCP server can do everything the CLI can do non-interactively.
For interactive/streaming commands (watch, exec, open, follow-logs) it tells the
user the exact CLI command to run instead of trying to proxy it.
For visual operations (resize dialog, live log stream, setup wizard UI) it
recommends `klight ui`.

Usage:
  klight mcp                          # start stdio server

Claude Desktop — ~/.config/claude/claude_desktop_config.json
  (macOS: ~/Library/Application Support/Claude/claude_desktop_config.json)
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

# ---------------------------------------------------------------------------
# Server + instructions
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "klight",
    instructions="""
You are a klight assistant. klight manages isolated Kubernetes dev environments —
every developer gets their own namespace (env-<name>) with services and infra
auto-wired. No K8s YAML knowledge needed.

─── Three workflows ───────────────────────────────────────────────────────────

World 1 — Local (user has cloned repos):
  1. local_setup       → set up minikube cluster (first time only)
  2. preload_infra     → pull postgres/kafka/redis into minikube (optional, avoids ImagePullBackOff)
  3. local_build_load  → docker build + minikube image load (per service)
  4. deploy_from_repos → deploy all services from their klight.yaml files

World 2 — Team sync (CI images, no local clone needed):
  1. sync_team          → download klight-team.yaml from a URL
  2. deploy_environment → deploy a named profile (store, full, …)

World 3 — Remote cluster (EKS / GKE / AKS):
  DevOps (once on the cluster):
  1. setup_remote_cluster → creates SA + RBAC + 1-year token
  Dev:
  2. connect_remote       → register the cluster URL + token locally
  3. switch_target        → switch to remote
  4. deploy_environment   → same as World 2

─── What the MCP can do ───────────────────────────────────────────────────────

Tools available here (call them directly):
  local_setup, preload_infra, local_build_load
  deploy_environment, deploy_from_repos
  service_status, get_logs, get_unready
  replace_service, restore_service
  destroy_environment
  init_service, sync_team
  connect_remote, setup_remote_cluster, switch_target
  run_preflight

─── What requires the CLI (tell the user to run these) ────────────────────────

These commands are interactive or stream output — they cannot run inside MCP:
  klight watch <svc> --env <name> --path <dir>   # hot reload on file change
  klight exec  <svc> --env <name>                # shell into a pod
  klight open  <svc> --env <name>                # port-forward + open browser
  klight logs  <svc> --env <name> -f             # follow/stream logs (use get_logs for a snapshot)

─── What works better in the UI (tell the user: klight ui) ────────────────────

  - Live streaming logs (auto-refreshes)
  - Cluster resize dialog (visual, with sizing estimate)
  - Setup wizard (GitHub scan → klight.yaml → klight-team.yaml, all in one flow)
  - Visual environment overview with service cards

─── Rules ─────────────────────────────────────────────────────────────────────

1. Never invent behavior. Every tool here maps 1:1 to a real klight CLI command.
2. If a user asks for something you can't do: give them the exact CLI command
   or say "run klight ui for this".
3. Always ask the user to confirm before calling destroy_environment.
4. If info is missing (env name, repo path, profile), ask before calling a tool.
5. Read klight://cluster before any deployment to confirm the right target.
6. Read klight://environments to understand current state before taking action.
7. If a deployment fails, call get_unready to get the fix hint.
""",
)

_ENV = {**os.environ, "NO_COLOR": "1"}


def _klight(*args: str, timeout: int = 300) -> str:
    """Run klight CLI, return combined stdout+stderr as plain text."""
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
# Resources — context Claude reads automatically before answering
# ---------------------------------------------------------------------------


@mcp.resource("klight://cluster")
def cluster_resource() -> str:
    """Current cluster target (local/remote), CPUs, RAM, and minikube status."""
    target = _klight("target")
    status = _klight("local", "status")
    return f"=== Active cluster target ===\n{target}\n\n=== Local cluster status ===\n{status}"


@mcp.resource("klight://environments")
def environments_resource() -> str:
    """All active klight environments and the pod status of their services."""
    result = subprocess.run(
        ["kubectl", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True, text=True, env=_ENV,
    )
    all_ns = result.stdout.split()
    env_ns = [ns for ns in all_ns if ns.startswith("env-")]
    if not env_ns:
        return "No active environments. Use deploy_environment or deploy_from_repos to create one."
    lines = [f"Active environments ({len(env_ns)}):"]
    for ns in env_ns:
        env_name = ns.removeprefix("env-")
        ps_out = _klight("ps", "--env", env_name)
        lines.append(f"\n--- env-{env_name} ---\n{ps_out}")
    return "\n".join(lines)


@mcp.resource("klight://team-yaml")
def team_yaml_resource() -> str:
    """Current cached klight-team.yaml — synced via klight sync."""
    cache_path = Path.home() / ".klight" / "team.yaml"
    if not cache_path.exists():
        return (
            "No klight-team.yaml cached yet.\n"
            "To sync: call sync_team(url=<raw GitHub URL to klight-team.yaml>)\n"
            "To create one: use the Setup Wizard in the UI (klight ui) or call init_service per repo."
        )
    return cache_path.read_text()


@mcp.resource("klight://capabilities")
def capabilities_resource() -> str:
    """Complete map of what MCP can do, what needs the CLI, and what's in the UI."""
    return """\
=== MCP tools (call directly) ===

Setup:
  local_setup(cpus, memory, profile)       # first-time minikube cluster
  preload_infra(profile, only)             # pull infra images into minikube
  local_build_load(service, repo_path)     # docker build + minikube load
  connect_remote(url, token, kubeconfig)   # register a remote cluster
  setup_remote_cluster()                   # DevOps: create SA + RBAC + token on current cluster
  switch_target(target)                    # switch local / remote / context name

Deploy:
  deploy_environment(profile, env_name)    # World 2/3: from synced klight-team.yaml
  deploy_from_repos(repo_paths, env_name)  # World 1: from local klight.yaml files
  run_preflight(env_name, profile)         # check image availability before deploy

Observe:
  service_status(env_name)                 # pod status table
  get_logs(service, env_name, tail, since) # snapshot of recent logs (not streaming)
  get_unready(env_name)                    # broken services + fix hints

Operate:
  replace_service(service, env_name, path) # hot-swap local build into running env
  restore_service(service, env_name)       # revert to CI image
  destroy_environment(env_name)            # delete env namespace (confirm first!)
  init_service(repo_path)                  # generate klight.yaml for a repo
  sync_team(url)                           # download klight-team.yaml

=== CLI only (interactive / streaming — tell user to run in terminal) ===

  klight watch <svc> --env <name> --path <dir>   # hot reload on file change
  klight exec  <svc> --env <name>                # interactive shell into pod
  klight open  <svc> --env <name>                # port-forward + open browser
  klight logs  <svc> --env <name> -f             # stream/follow logs live

=== UI (klight ui → http://localhost:7700) ===

  - Live streaming logs per service
  - Cluster resize with sizing estimate banner
  - Setup Wizard: GitHub scan → klight.yaml generation → klight-team.yaml
  - Visual service cards with status and resource usage
"""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

# ── Local cluster setup (World 1) ───────────────────────────────────────────

@mcp.tool()
def local_setup(cpus: int = 2, memory: int = 4096, profile: str = "klight-demo") -> str:
    """
    Create and start the local minikube cluster for klight (first-time setup).
    Run this once before using World 1 (deploy_from_repos).

    Args:
        cpus: Number of CPUs to allocate (default 2, recommend 4 for large profiles)
        memory: RAM in MB (default 4096; kafka needs at least 3072)
        profile: minikube profile name (default "klight-demo")
    """
    return _klight("local", "setup", "--cpus", str(cpus), "--memory", str(memory), "--profile", profile, timeout=300)


@mcp.tool()
def preload_infra(profile: str = "klight-demo", only: str = "") -> str:
    """
    Pull all infrastructure images (postgres, kafka, redis, etc.) into minikube.
    Run this after local_setup to avoid ImagePullBackOff on first deploy.

    Args:
        profile: minikube profile name (default "klight-demo")
        only: Comma-separated list of infra names to pull, e.g. "postgres,redis".
              Empty = pull all catalog images.
    """
    args = ["local", "preload-infra", "--profile", profile]
    if only:
        args += ["--only", only]
    return _klight(*args, timeout=600)


@mcp.tool()
def local_build_load(service: str, repo_path: str, profile: str = "klight-demo") -> str:
    """
    Build a service's Docker image and load it into minikube (World 1).
    Run this for each service before deploy_from_repos, or after code changes
    when not using klight watch.

    For continuous hot reload on file change, use the CLI instead:
      klight watch <service> --env <name> --path <repo_path>

    Args:
        service: Service name matching klight.yaml (e.g. "inventory-api")
        repo_path: Absolute path to the service repo containing a Dockerfile
        profile: minikube profile name (default "klight-demo")
    """
    return _klight("local", "build-load", service, "--path", repo_path, "--profile", profile, timeout=300)


# ── Remote cluster setup (World 3) ──────────────────────────────────────────

@mcp.tool()
def setup_remote_cluster() -> str:
    """
    DevOps: configure the CURRENT kubectl cluster for klight access.
    Creates a ServiceAccount, ClusterRole, and 1-year token that developers
    can use with connect_remote. Run this once on the team's EKS/GKE/AKS cluster.

    Prerequisites: kubectl context must already point to the remote cluster.
    To switch context first, call switch_target(target=<context-name>).
    """
    return _klight("cluster", "setup-remote", timeout=60)


@mcp.tool()
def connect_remote(url: str = "", token: str = "", kubeconfig_path: str = "") -> str:
    """
    Register a remote Kubernetes cluster so klight can target it.
    Use one of:
      - url + token: from the output of setup_remote_cluster
      - kubeconfig_path: path to an existing kubeconfig file

    After connecting, call switch_target(target="klight-remote") to activate it.

    Args:
        url: Kubernetes API server URL (e.g. "https://k8s.company.com")
        token: Service account token from setup_remote_cluster
        kubeconfig_path: Absolute path to a kubeconfig file (alternative to url+token)
    """
    if kubeconfig_path:
        return _klight("connect", "--kubeconfig", kubeconfig_path)
    if url and token:
        return _klight("connect", "--url", url, "--token", token)
    return (
        "ERROR: provide either (url + token) or kubeconfig_path.\n"
        "Get url + token by running setup_remote_cluster() on your cluster first."
    )


# ── Deploy ───────────────────────────────────────────────────────────────────

@mcp.tool()
def deploy_environment(profile: str, env_name: str, timeout: int = 300) -> str:
    """
    Deploy a profile to a named Kubernetes environment (World 2 / World 3).
    Uses CI images from the synced klight-team.yaml. No local repos needed.
    Call sync_team first if you haven't synced the team config yet.

    Args:
        profile: Profile name from klight-team.yaml (e.g. "store", "full")
        env_name: Environment name — creates namespace env-<name> (e.g. "alice", "dev")
        timeout: Seconds to wait for all pods ready (default 300)
    """
    return _klight("up", profile, "--env", env_name, "--timeout", str(timeout), timeout=timeout + 30)


@mcp.tool()
def deploy_from_repos(repo_paths: list[str], env_name: str, timeout: int = 300) -> str:
    """
    Deploy services from local repository paths (World 1).
    Each repo must have a klight.yaml. Runs local images built with local_build_load.
    Auto-generates K8s manifests and starts infra in dependency order.

    Typical World 1 flow:
      1. local_setup()
      2. preload_infra()
      3. local_build_load() per service
      4. deploy_from_repos(repo_paths, env_name)

    Args:
        repo_paths: Absolute paths to service repos with klight.yaml
        env_name: Environment name (e.g. "dev", "alice")
        timeout: Seconds to wait for all pods ready (default 300)
    """
    return _klight("from-repos", *repo_paths, "--env", env_name, "--timeout", str(timeout), timeout=timeout + 30)


@mcp.tool()
def run_preflight(env_name: str = "", profile: str = "") -> str:
    """
    Check image availability before deploying — finds missing images early.
    Run this before deploy_environment or deploy_from_repos to avoid a failed deploy.

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


# ── Observe ──────────────────────────────────────────────────────────────────

@mcp.tool()
def service_status(env_name: str) -> str:
    """
    Show pod and service status for an environment as a formatted table.
    For a live visual overview, use: klight ui → http://localhost:7700

    Args:
        env_name: Environment name (e.g. "tienda", "dev", "alice")
    """
    return _klight("ps", "--env", env_name)


@mcp.tool()
def get_logs(service: str, env_name: str, tail: int = 100, since: str = "") -> str:
    """
    Get a snapshot of recent logs from a service.
    For live streaming logs, use the CLI or UI:
      CLI: klight logs <service> --env <env> -f
      UI:  klight ui → click the service → Logs tab

    Args:
        service: Service name (e.g. "inventory-api", "store-web")
        env_name: Environment name
        tail: Number of lines to return (default 100)
        since: Return logs newer than this, e.g. "5m", "1h" (optional)
    """
    args = ["logs", service, "--env", env_name, "--tail", str(tail)]
    if since:
        args += ["--since", since]
    return _klight(*args)


@mcp.tool()
def get_unready(env_name: str) -> str:
    """
    Show services that are not Ready, with a specific fix hint for each.
    Always call this when a deployment seems stuck or a service is crashing.

    Args:
        env_name: Environment name
    """
    return _klight("unready", "--env", env_name)


# ── Operate ──────────────────────────────────────────────────────────────────

@mcp.tool()
def replace_service(service: str, env_name: str, path: str) -> str:
    """
    Hot-swap a running service with a locally built image.
    Builds, loads into minikube, and restarts the pod. Other services keep CI images.

    For continuous hot reload on every file save, use the CLI:
      klight watch <service> --env <env> --path <path>

    Args:
        service: Service to replace (e.g. "store-api")
        env_name: Environment name
        path: Absolute path to repo with Dockerfile
    """
    return _klight("replace", service, "--env", env_name, "--with", path, timeout=180)


@mcp.tool()
def restore_service(service: str, env_name: str) -> str:
    """
    Restore a service to its CI image, undoing a previous replace_service call.

    Args:
        service: Service name to restore
        env_name: Environment name
    """
    return _klight("restore", service, "--env", env_name)


@mcp.tool()
def destroy_environment(env_name: str) -> str:
    """
    Destroy an environment — deletes the namespace and ALL its resources.
    THIS IS IRREVERSIBLE. Always confirm with the user before calling this.

    Args:
        env_name: Environment name to destroy
    """
    return _klight("destroy", env_name, "--yes")


# ── Config ───────────────────────────────────────────────────────────────────

@mcp.tool()
def init_service(repo_path: str) -> str:
    """
    Scan a service repository and auto-generate a klight.yaml file.
    Detects language, port, health endpoint, and infrastructure dependencies.
    For an interactive wizard with GitHub scanning, use: klight ui → Setup Wizard tab.

    Args:
        repo_path: Absolute path to the service repo
    """
    return _klight("init", repo_path, "--yes")


@mcp.tool()
def sync_team(url: str = "") -> str:
    """
    Download and cache the team's klight-team.yaml from a URL.
    Required before deploy_environment (World 2 / World 3).
    To generate a klight-team.yaml from scratch, use: klight ui → Setup Wizard tab.

    Args:
        url: Raw URL to klight-team.yaml. Empty = re-sync from last used URL.
    """
    args = ["sync"]
    if url:
        args.append(url)
    return _klight(*args)


@mcp.tool()
def switch_target(target: str) -> str:
    """
    Switch the active cluster target. Check current target via klight://cluster resource.

    Args:
        target: "local" (minikube klight-demo), "remote" / "klight-remote"
                (configured remote), or any kubectl context name
    """
    return _klight("use", target)
