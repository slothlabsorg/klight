"""
klight UI — web dashboard.
FastAPI backend + single-page HTML. No build step.

Start: klight ui → http://localhost:7700

Tabs:
  Environments — live status of all klight environments
  Setup        — wizard: connect git platform, scan repos, generate klight.yaml
"""

from __future__ import annotations
import json, subprocess, os, urllib.request, base64, time, yaml, socket
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# `klight ui` may be launched from a shell that never sourced the user's
# profile (no login-shell rc files), so tools installed via Homebrew
# (minikube, kubectl...) can end up missing from PATH even though `klight`
# itself resolved fine. Make sure every subprocess this server spawns can
# find them, regardless of how the server process itself was started.
for _p in ("/opt/homebrew/bin", str(Path.home() / ".local" / "bin")):
    if _p not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

app = FastAPI(title="klight UI", docs_url=None, redoc_url=None)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ─── Local dev-loop process manager (non-k8s helpers: frontend dev servers,   ──
# ─── plugin watch builds, proxies) — separate from the k8s services above.    ──
# klight itself knows nothing about any specific project's services. The
# actual catalog of local processes (and which k8s service each port-forward
# belongs to, for the auto-bounce-after-rebuild below) lives in a JSON file
# supplied by whoever's project this is - point KLIGHT_LOCAL_PROCESSES_FILE at
# it. With no file configured, this feature is simply empty/inert.
#
# Expected JSON shape:
# {
#   "processes": {
#     "<key>": {"label": str, "cmd": str, "cwd": str|null, "port": int|null, "needs_nvm": bool}
#   },
#   "service_port_forwards": {"<k8s-service-name>": "<process key>"}
# }
PROC_LOG_DIR = Path(os.environ.get("KLIGHT_UI_LOG_DIR", "/tmp/klight-ui-procs"))
PROC_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_processes_config() -> dict:
    path = os.environ.get("KLIGHT_LOCAL_PROCESSES_FILE")
    if not path:
        return {"processes": {}, "service_port_forwards": {}}
    p = Path(path).expanduser()
    if not p.exists():
        return {"processes": {}, "service_port_forwards": {}}
    try:
        data = json.loads(p.read_text())
        processes = data.get("processes", {})
        for meta in processes.values():
            if meta.get("cwd"):
                meta["cwd"] = str(Path(meta["cwd"]).expanduser())
        return {
            "processes": processes,
            "service_port_forwards": data.get("service_port_forwards", {}),
        }
    except Exception:
        return {"processes": {}, "service_port_forwards": {}}


_local_cfg = _load_local_processes_config()
LOCAL_PROCESSES: dict[str, dict] = _local_cfg["processes"]
# `kubectl port-forward` doesn't survive its target pod being replaced (rollout
# restart kills the tunnel) - maps k8s service name -> the LOCAL_PROCESSES key
# for its port-forward, so a rebuild can bounce it instead of leaving it stale.
SERVICE_PORT_FORWARD: dict[str, str] = _local_cfg["service_port_forwards"]

PROC_STATE: dict[str, subprocess.Popen] = {}


def _build_shell_cmd(meta: dict) -> str:
    if not meta.get("needs_nvm"):
        return meta["cmd"]
    return (
        'export NVM_DIR="$HOME/.nvm"; '
        '[ -s "/opt/homebrew/opt/nvm/nvm.sh" ] && . "/opt/homebrew/opt/nvm/nvm.sh"; '
        'nvm use 24 >/dev/null 2>&1 || nvm use default >/dev/null 2>&1; '
        f'exec {meta["cmd"]}'
    )


def _port_open(port: int, host: str = "localhost", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _tail_log(key: str, lines: int = 5) -> str:
    log_path = PROC_LOG_DIR / f"{key}.log"
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(errors="ignore")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        return ""


def _pids_on_port(port: int) -> list[int]:
    r = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split()] if r.returncode == 0 else []


def _is_running(key: str, meta: dict) -> bool:
    """A process we spawned is definitely running if our handle says so. But it
    may also have been started outside this klight-ui instance (e.g. by hand,
    or a previous klight-ui process) - for anything with a port, the port
    actually being open is the more reliable signal either way."""
    proc = PROC_STATE.get(key)
    if proc is not None and proc.poll() is None:
        return True
    if meta.get("port"):
        return _port_open(meta["port"])
    return False


@app.get("/api/local/processes")
def list_local_processes():
    out = []
    for key, meta in LOCAL_PROCESSES.items():
        running = _is_running(key, meta)
        out.append({
            "key": key,
            "label": meta["label"],
            "running": running,
            "port": meta.get("port"),
            "port_ok": _port_open(meta["port"]) if (running and meta.get("port")) else None,
            "log_tail": _tail_log(key),
        })
    return out


@app.post("/api/local/processes/{key}/start")
def start_local_process(key: str):
    if key not in LOCAL_PROCESSES:
        raise HTTPException(404, f"Unknown process '{key}'")
    meta = LOCAL_PROCESSES[key]
    if _is_running(key, meta):
        return {"ok": True, "already_running": True}

    if meta.get("cwd") and not Path(meta["cwd"]).exists():
        raise HTTPException(400, f"Path not found: {meta['cwd']} (set KLIGHT_DEV_HOME or edit LOCAL_PROCESSES)")

    log_path = PROC_LOG_DIR / f"{key}.log"
    logf = open(log_path, "w")
    proc = subprocess.Popen(
        ["bash", "-lc", _build_shell_cmd(meta)],
        cwd=meta.get("cwd"), stdout=logf, stderr=subprocess.STDOUT,
    )
    PROC_STATE[key] = proc
    return {"ok": True, "pid": proc.pid}


@app.post("/api/local/processes/{key}/stop")
def stop_local_process(key: str):
    if key not in LOCAL_PROCESSES:
        raise HTTPException(404, f"Unknown process '{key}'")
    meta = LOCAL_PROCESSES[key]

    proc = PROC_STATE.get(key)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        PROC_STATE.pop(key, None)

    # Also clean up anything holding the port that we didn't spawn ourselves
    # (e.g. started by hand before this klight-ui instance existed).
    if meta.get("port"):
        for pid in _pids_on_port(meta["port"]):
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass

    return {"ok": True}

BUILT_IN_CATALOG = {
    "postgres", "kafka", "redis", "mongodb",
    "rabbitmq", "localstack", "elasticsearch",
}
MANIFESTS_DIR = os.environ.get("KLIGHT_MANIFESTS_DIR",
    str(Path(__file__).parent.parent / "manifests"))


# ─── K8s helpers ─────────────────────────────────────────────────────────────

def kubectl(*args):
    r = subprocess.run(["kubectl"] + list(args), capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return r.stdout.strip()


def kubectl_ns(ns, *args):
    return kubectl("-n", ns, *args)


# ─── Environments API ─────────────────────────────────────────────────────────

@app.get("/api/envs")
def list_envs():
    data = kubectl("get", "namespaces", "-l", "klight.env", "-o", "json")
    if not isinstance(data, dict):
        return []
    return [
        {
            "name": i["metadata"]["labels"]["klight.env"],
            "namespace": i["metadata"]["name"],
            "status": i["status"]["phase"],
            "age": i["metadata"].get("creationTimestamp", ""),
        }
        for i in data.get("items", [])
    ]


@app.get("/api/envs/{env_name}/services")
def list_services(env_name: str):
    ns = f"env-{env_name}"
    data = kubectl_ns(ns, "get", "pods", "-o", "json")
    if not isinstance(data, dict):
        return []
    services = {}
    for pod in data.get("items", []):
        labels = pod["metadata"].get("labels", {})
        svc = labels.get("app") or pod["metadata"]["name"]
        phase = pod["status"].get("phase", "Unknown")
        if phase in ("Succeeded", "Completed"):
            continue
        cs = pod["status"].get("containerStatuses", [])
        ready = sum(1 for c in cs if c.get("ready"))
        total = len(cs) or 1
        restarts = sum(c.get("restartCount", 0) for c in cs)
        problem = None
        for c in cs:
            s = c.get("state", {})
            if "waiting" in s and s["waiting"].get("reason") not in (None, "ContainerCreating"):
                problem = s["waiting"]["reason"]
                break
        if svc not in services:
            services[svc] = {
                "name": svc, "ready": ready, "total": total,
                "status": problem or phase,
                "healthy": (phase == "Running" and ready == total),
                "restarts": restarts,
            }
    return list(services.values())


@app.get("/api/envs/{env_name}/services/{svc}/logs")
def get_logs(env_name: str, svc: str, lines: int = 150):
    ns = f"env-{env_name}"
    r = subprocess.run(
        ["kubectl", "logs", "-n", ns, f"deployment/{svc}", f"--tail={lines}"],
        capture_output=True, text=True,
    )
    return {"logs": r.stdout or r.stderr, "service": svc}


class RebuildRequest(BaseModel):
    path: str    # absolute path to the service's repo (must contain klight.yaml)
    profile: str = "klight-demo"


@app.post("/api/envs/{env_name}/services/{svc}/rebuild")
def rebuild_service(env_name: str, svc: str, req: RebuildRequest):
    """
    One-button dev loop: build (mvn/gradle/docker, whatever klight.yaml's
    `build.command` says, or a plain `docker build` if none) → load into
    minikube → restart the pod → BLOCK until the rollout actually reports
    Ready (not just "restart triggered"), so the caller gets a true green/red
    signal instead of having to poll logs by hand.
    """
    from klight.commands.watch import _build_image, _load_to_minikube
    from klight.schema import KlightConfig

    repo_path = Path(req.path).expanduser()
    klf = repo_path / "klight.yaml"
    if not klf.exists():
        raise HTTPException(400, f"No klight.yaml at {repo_path}")

    cfg = KlightConfig.from_file(klf)
    ns = f"env-{env_name}"
    t0 = time.time()

    if not _build_image(cfg, repo_path):
        raise HTTPException(500, "Build failed — check the service's own build output/logs")

    if not _load_to_minikube(cfg.effective_image(), req.profile):
        raise HTTPException(500, "minikube image load failed")

    subprocess.run(["kubectl", "-n", ns, "rollout", "restart", f"deployment/{svc}"],
                   capture_output=True, text=True)

    r = subprocess.run(
        ["kubectl", "-n", ns, "rollout", "status", f"deployment/{svc}", "--timeout=600s"],
        capture_output=True, text=True,
    )
    elapsed = round(time.time() - t0)
    if r.returncode != 0:
        raise HTTPException(500, f"Rollout did not go Ready within timeout ({elapsed}s elapsed): {(r.stdout or r.stderr)[-1000:]}")

    # A rollout restart replaces the pod, which kills any `kubectl port-forward`
    # tunnel pointed at it - bounce the matching one so :8080/:8082 keep working
    # without the user having to notice and do it by hand.
    pf_key = SERVICE_PORT_FORWARD.get(svc)
    if pf_key:
        stop_local_process(pf_key)
        time.sleep(1)
        start_local_process(pf_key)

    return {"ok": True, "service": svc, "elapsed_seconds": elapsed}


@app.delete("/api/envs/{env_name}")
def destroy_env(env_name: str):
    ns = f"env-{env_name}"
    r = subprocess.run(
        ["kubectl", "delete", "namespace", ns, "--ignore-not-found"],
        capture_output=True, text=True,
    )
    return {"ok": r.returncode == 0}


# ─── Setup wizard API ─────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    token: str
    org: str
    platform: str = "github"     # github | gitlab | bitbucket


class GenerateRequest(BaseModel):
    token: str
    org: str
    platform: str = "github"
    selected_repos: list[str]
    registry: str                  # e.g. ghcr.io/slothlabsorg or 123.dkr.ecr.us-east-1.amazonaws.com/co
    infra_repo: str = ""
    image_tag: str = "main"


class TeamYamlRequest(BaseModel):
    org: str
    registry: str
    services: list[dict]
    profiles: dict
    infra_repo: str = ""
    image_tag: str = "main"


def _gh_api(token: str, path: str) -> dict | list | None:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _gl_api(token: str, path: str) -> dict | list | None:
    url = f"https://gitlab.com/api/v4{path}"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _get_file_content(platform: str, token: str, org: str, repo: str, filepath: str) -> str | None:
    if platform == "github":
        data = _gh_api(token, f"/repos/{org}/{repo}/contents/{filepath}")
        if isinstance(data, dict) and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    elif platform == "gitlab":
        encoded = filepath.replace("/", "%2F")
        data = _gl_api(token, f"/projects/{org}%2F{repo}/repository/files/{encoded}/raw?ref=main")
        if isinstance(data, str):
            return data
    return None


@app.post("/api/setup/scan")
def scan_repos(req: ScanRequest):
    """List repos from the platform and check klight.yaml / Dockerfile presence."""
    repos = []
    if req.platform == "github":
        data = _gh_api(req.token, f"/orgs/{req.org}/repos?per_page=100&sort=updated")
        if not isinstance(data, list):
            # Fall back to user repos (for personal accounts)
            data = _gh_api(req.token, f"/users/{req.org}/repos?per_page=100")
        if not isinstance(data, list):
            raise HTTPException(400, "Could not list repos. Check token and org name.")
        for r in data:
            name = r["name"]
            klight_raw = _get_file_content("github", req.token, req.org, name, "klight.yaml")
            has_klight = bool(klight_raw)
            has_dockerfile = bool(_get_file_content("github", req.token, req.org, name, "Dockerfile"))
            has_deploy = any([
                _get_file_content("github", req.token, req.org, name, "deploy/base/kustomization.yaml"),
                _get_file_content("github", req.token, req.org, name, "k8s/kustomization.yaml"),
            ])
            unknown_needs: list[str] = []
            if klight_raw:
                try:
                    kd = yaml.safe_load(klight_raw) or {}
                    for n in (kd.get("needs") or []):
                        if str(n) not in BUILT_IN_CATALOG:
                            unknown_needs.append(str(n))
                except Exception:
                    pass
            repos.append({
                "name": name,
                "description": r.get("description", ""),
                "has_klight": has_klight,
                "has_dockerfile": has_dockerfile,
                "has_deploy_folder": has_deploy,
                "url": r.get("html_url", ""),
                "is_service": has_dockerfile or has_klight,
                "unknown_needs": unknown_needs,
            })
    elif req.platform == "gitlab":
        data = _gl_api(req.token, f"/groups/{req.org}/projects?per_page=100")
        if isinstance(data, list):
            for r in data:
                name = r.get("path", r.get("name", ""))
                repos.append({
                    "name": name,
                    "description": r.get("description", ""),
                    "has_klight": False,
                    "has_dockerfile": False,
                    "has_deploy_folder": False,
                    "url": r.get("web_url", ""),
                    "is_service": True,
                })
    return {"repos": repos, "total": len(repos)}


@app.post("/api/setup/generate")
def generate_klight_yamls(req: GenerateRequest):
    """
    For each selected repo without klight.yaml, generate one.
    Uses registry prefix — doesn't need to know CI details.
    """
    results = []
    catalog_warnings: list[dict] = []
    for repo_name in req.selected_repos:
        existing = _get_file_content(req.platform, req.token, req.org, repo_name, "klight.yaml")
        if existing:
            unknown: list[str] = []
            try:
                kd = yaml.safe_load(existing) or {}
                for n in (kd.get("needs") or []):
                    if str(n) not in BUILT_IN_CATALOG:
                        unknown.append(str(n))
            except Exception:
                pass
            if unknown:
                catalog_warnings.append({"repo": repo_name, "unknown_needs": unknown})
            results.append({"repo": repo_name, "status": "exists", "yaml": existing})
            continue

        # Detect port from Dockerfile
        dockerfile = _get_file_content(req.platform, req.token, req.org, repo_name, "Dockerfile") or ""
        import re
        port_match = re.search(r"EXPOSE\s+(\d+)", dockerfile)
        port = int(port_match.group(1)) if port_match else 8080

        # Health check heuristic
        health = "/actuator/health" if "spring" in dockerfile.lower() or "gradle" in dockerfile.lower() else "/health"

        # Detect manifest folder
        manifest = ""
        if _get_file_content(req.platform, req.token, req.org, repo_name, "deploy/overlays/dev/kustomization.yaml"):
            manifest = "./deploy/overlays/dev"
        elif _get_file_content(req.platform, req.token, req.org, repo_name, "deploy/base/kustomization.yaml"):
            manifest = "./deploy/base"
        elif _get_file_content(req.platform, req.token, req.org, repo_name, "k8s/kustomization.yaml"):
            manifest = "./k8s"

        # Image: registry/repo-name:tag
        image = f"{req.registry}/{repo_name}:{req.image_tag}"

        yaml_lines = [
            "# yaml-language-server: $schema=https://slothlabsorg.github.io/klight/schema/klight.yaml.json",
            f"name: {repo_name}",
            f"port: {port}",
            f"health: {health}",
            f"image: {image}",
        ]
        if manifest:
            yaml_lines.append(f"manifest: {manifest}")
        yaml_lines.extend([
            "",
            "# Add infra needs (postgres, kafka, redis, localstack, etc.)",
            "# needs: [postgres, kafka]",
            "",
            "# Add env vars your code reads:",
            "# env:",
            "#   DB_HOST: postgres",
        ])
        yaml_content = "\n".join(yaml_lines) + "\n"
        results.append({"repo": repo_name, "status": "generated", "yaml": yaml_content})

    return {"results": results, "catalog_warnings": catalog_warnings}


@app.post("/api/setup/team-yaml")
def generate_team_yaml(req: TeamYamlRequest):
    """Generate klight-team.yaml content."""
    import yaml
    infra_repo = req.infra_repo or (req.services[0]["repo"].rsplit("/", 1)[0] + "/infra" if req.services else "")
    data = {
        "version": "1",
        "team": req.org.lower(),
        "source": {
            "type": "git",
            "url": f"https://github.com/{req.org}/{req.infra_repo}" if req.infra_repo else "",
            "branch": "main",
        },
        "targets": {"local": "klight-demo", "remote": ""},
        "services": [
            {"name": s["name"], "image": f"{req.registry}/{s['repo_name']}:{req.image_tag}",
             "repo": s.get("url", "")}
            for s in req.services
        ],
        "profiles": req.profiles,
    }
    return {"yaml": yaml.dump(data, default_flow_style=False, allow_unicode=True)}


class PRRequest(BaseModel):
    token: str
    org: str
    repo: str
    yaml_content: str


@app.post("/api/setup/create-pr")
def create_pr(req: PRRequest):
    """Create a PR in a repo to add klight.yaml."""
    import base64

    def api(method, path, data=None):
        url = f"https://api.github.com{path}"
        body = json.dumps(data).encode() if data else None
        r = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {req.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }, method=method)
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    try:
        repo_info = api("GET", f"/repos/{req.org}/{req.repo}")
        default_branch = repo_info["default_branch"]
        ref = api("GET", f"/repos/{req.org}/{req.repo}/git/ref/heads/{default_branch}")
        sha = ref["object"]["sha"]

        branch = "klight/add-klight-yaml"
        api("POST", f"/repos/{req.org}/{req.repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha})

        api("PUT", f"/repos/{req.org}/{req.repo}/contents/klight.yaml", {
            "message": "Add klight.yaml for environment management",
            "content": base64.b64encode(req.yaml_content.encode()).decode(),
            "branch": branch,
        })

        pr = api("POST", f"/repos/{req.org}/{req.repo}/pulls", {
            "title": "Add klight.yaml",
            "body": "Generated by `klight setup`. See [klight docs](https://github.com/slothlabsorg/klight).",
            "head": branch,
            "base": default_branch,
        })
        return {"ok": True, "pr_url": pr["html_url"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Local cluster API ───────────────────────────────────────────────────────

@app.get("/api/local/cluster-info")
def cluster_info():
    """Return current minikube cluster CPUs, memory, and status."""
    profile = os.environ.get("KLIGHT_MINIKUBE_PROFILE", "klight-demo")
    r = subprocess.run(
        ["minikube", "profile", "list", "-o", "json"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout)
            for p in data.get("valid", []):
                if p.get("Name") == profile:
                    conf = p.get("Config", {})
                    return {
                        "profile": profile,
                        "cpus": conf.get("CPUs", 0),
                        "memory_mb": conf.get("Memory", 0),
                        "status": p.get("Status", "Unknown"),
                    }
        except Exception:
            pass
    config_path = Path.home() / ".minikube" / "profiles" / profile / "config.json"
    if config_path.exists():
        try:
            conf = json.loads(config_path.read_text())
            rs = subprocess.run(
                ["minikube", "status", f"--profile={profile}", "-o", "json"],
                capture_output=True, text=True,
            )
            status_val = "Unknown"
            if rs.returncode == 0:
                try:
                    status_val = json.loads(rs.stdout).get("Host", "Unknown")
                except Exception:
                    pass
            return {
                "profile": profile,
                "cpus": conf.get("CPUs", 0),
                "memory_mb": conf.get("Memory", 0),
                "status": status_val,
            }
        except Exception:
            pass
    return {"profile": profile, "cpus": 0, "memory_mb": 0, "status": "Unknown"}


@app.get("/api/local/sizing/{profile_name}")
def sizing(profile_name: str):
    """Estimate memory needs for a profile."""
    try:
        from klight.commands.local import _estimate_profile_mb
        return _estimate_profile_mb(profile_name)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/local/profiles")
def list_profiles():
    """List available profiles from the synced team."""
    try:
        from klight.commands.sync import get_active_team
        team = get_active_team()
        if not team:
            return {"profiles": []}
        return {"profiles": list(team.get("profiles", {}).keys())}
    except Exception:
        return {"profiles": []}


class ResizeRequest(BaseModel):
    memory_mb: int
    cpus: int = 2
    profile: str = "klight-demo"


@app.post("/api/local/resize")
def resize_cluster(req: ResizeRequest):
    """Stop and restart minikube with new resources."""
    import shutil
    if not shutil.which("minikube"):
        raise HTTPException(400, "minikube not found in PATH")
    subprocess.run(
        ["minikube", "stop", f"--profile={req.profile}"],
        capture_output=True, text=True,
    )
    r = subprocess.run(
        ["minikube", "start",
         f"--profile={req.profile}",
         "--driver=docker",
         f"--cpus={req.cpus}",
         f"--memory={req.memory_mb}",
         "--kubernetes-version=v1.30.0"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise HTTPException(500, f"Resize failed: {r.stderr[:500]}")
    kubeconfig_path = "/tmp/klight-demo-kubeconfig.yaml"
    r2 = subprocess.run(
        ["minikube", "-p", req.profile, "kubectl", "--", "config", "view", "--raw"],
        capture_output=True, text=True,
    )
    if r2.returncode == 0 and r2.stdout:
        Path(kubeconfig_path).write_text(r2.stdout)
    return {"ok": True, "profile": req.profile, "cpus": req.cpus, "memory_mb": req.memory_mb}


# ─── Onboarding assistant API ─────────────────────────────────────────────────

@app.get("/api/onboarding/probe")
def onboarding_probe():
    """Detect the user's environment so the assistant skips questions it can answer.

    Returns capability flags used by the "Get started" tab:
      - kubectl_access: kubectl reaches a cluster (cluster-info ok)
      - local_cluster:  klight-demo minikube is running
      - has_team_yaml:  a klight-team.yaml has been synced (~/.klight)
      - active_target:  local / remote / custom (from klight target)
    """
    result = {
        "kubectl_access": False,
        "local_cluster": False,
        "has_team_yaml": False,
        "team_name": None,
        "profiles": [],
        "active_target": None,
    }

    # kubectl access (any reachable cluster)
    try:
        r = subprocess.run(["kubectl", "cluster-info"], capture_output=True, text=True, timeout=5)
        result["kubectl_access"] = r.returncode == 0
    except Exception:
        pass

    # local minikube cluster
    try:
        info = cluster_info()
        result["local_cluster"] = str(info.get("status", "")).lower() == "running"
    except Exception:
        pass

    # synced team.yaml
    try:
        from klight.commands.sync import get_active_team
        team = get_active_team()
        if team:
            result["has_team_yaml"] = True
            result["team_name"] = team.get("team")
            result["profiles"] = list(team.get("profiles", {}).keys())
    except Exception:
        pass

    # active cluster target (derived from kubectl current-context)
    try:
        r = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True, text=True, timeout=5,
        )
        ctx = r.stdout.strip()
        if ctx:
            if ctx == "klight-demo":
                result["active_target"] = "local"
            elif "remote" in ctx:
                result["active_target"] = "remote"
            else:
                result["active_target"] = ctx
    except Exception:
        pass

    return result


# ─── Mode API (REMOTE / LOCAL toggle) ─────────────────────────────────────────

MODE_FILE = Path.home() / ".devnext-mode"


@app.get("/api/mode")
def get_mode():
    """Return current backend mode."""
    try:
        mode = MODE_FILE.read_text().strip().lower() if MODE_FILE.exists() else "remote"
    except Exception:
        mode = "remote"
    return {"mode": mode}


class SetModeRequest(BaseModel):
    mode: str  # "local" or "remote"


@app.post("/api/mode")
def set_mode(req: SetModeRequest):
    """Switch backend mode."""
    if req.mode not in ("local", "remote"):
        raise HTTPException(400, "mode must be 'local' or 'remote'")
    MODE_FILE.write_text(req.mode + "\n")
    return {"ok": True, "mode": req.mode}


# ─── Gateway status API ───────────────────────────────────────────────────────

@app.get("/api/gateway/status")
def gateway_status():
    """Check if gateway proxy is running and show config."""
    pid_file = Path.home() / ".klight" / "gateway.pid"
    running = False
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # check if process exists
            running = True
        except (ValueError, ProcessLookupError, OSError):
            running = False

    # Read token status
    token_file = Path.home() / ".devnext-token"
    has_token = False
    try:
        has_token = token_file.exists() and len(token_file.read_text().strip()) > 10
    except Exception:
        pass

    return {
        "running": running,
        "pid": pid if running else None,
        "port": 4300,
        "has_token": has_token,
        "token_hint": "echo '<token>' > ~/.devnext-token" if not has_token else None,
    }


# ─── Companions YAML API (reads klight-companions.yaml) ──────────────────────

def _load_companions_yaml() -> dict:
    """Load companions from klight-companions.yaml (new format)."""
    search_paths = [
        Path.cwd() / "klight-companions.yaml",
        Path.home() / ".klight" / "klight-companions.yaml",
    ]
    for p in search_paths:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text())
                return data.get("companions", {}) if data else {}
            except Exception:
                pass
    return {}


@app.get("/api/companions")
def list_companions():
    """Return companion processes from klight-companions.yaml with live status."""
    companions = _load_companions_yaml()
    if not companions:
        # Fallback to old LOCAL_PROCESSES
        return list_local_processes()

    out = []
    for key, meta in companions.items():
        port = meta.get("port")
        running = _port_open(port) if port else False
        out.append({
            "key": key,
            "label": meta.get("label", key),
            "running": running,
            "port": port,
            "node": meta.get("node"),
            "cwd": meta.get("cwd", ""),
        })
    return out


# ─── HTML Frontend ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return open(Path(__file__).parent / "index.html").read() if (Path(__file__).parent / "index.html").exists() else HTML


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>klight</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { font-family: system-ui, sans-serif; background: #050d1f; color: #e2e8f0; }
  .dot-g { width:10px;height:10px;border-radius:50%;background:#22c55e;display:inline-block }
  .dot-r { width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block }
  .dot-y { width:10px;height:10px;border-radius:50%;background:#eab308;display:inline-block }
  pre { white-space:pre-wrap; word-break:break-all; font-size:12px; }
  input,select,textarea { background:#0d1b3e; border:1px solid #1a3060; border-radius:6px; padding:6px 10px; color:#e2e8f0; width:100%; }
  input:focus,select:focus,textarea:focus { outline:none; border-color:#B4FF3C; }
  #logs-panel { resize: vertical; overflow: hidden; min-height: 160px; max-height: 85vh; }
  #logs-content {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px; line-height: 1.5;
    white-space: pre-wrap; word-break: normal; overflow-wrap: anywhere;
  }
</style>
</head>
<body class="min-h-screen">
<header style="background:#050d1f;border-bottom:1px solid #1a3060" class="px-6 py-3 flex items-center gap-4">
  <img src="/static/images/klight-logo.png" class="h-8 w-8 rounded" alt="klight">
  <span class="font-bold text-xl" style="color:#B4FF3C">klight</span>
  <div class="ml-auto flex gap-2">
    <button onclick="tab('start')" id="tb-start" class="px-3 py-1 rounded text-sm" style="background:#B4FF3C;color:#050d1f">Get started</button>
    <button onclick="tab('envs')" id="tb-envs" class="px-3 py-1 rounded text-sm text-slate-300 hover:bg-slate-700">Environments</button>
    <button onclick="tab('setup')" id="tb-setup" class="px-3 py-1 rounded text-sm text-slate-300 hover:bg-slate-700">Setup Wizard</button>
    <button onclick="tab('about')" id="tb-about" class="px-3 py-1 rounded text-sm text-slate-300 hover:bg-slate-700">About</button>
  </div>
</header>

<!-- Cluster status bar (always visible) -->
<div id="cluster-bar" style="background:#0d1b3e;border-bottom:1px solid #1a3060" class="px-6 py-2 flex items-center gap-3 text-xs text-slate-400">
  <span>Cluster:</span>
  <span id="cb-name" class="text-slate-200 font-mono font-medium">—</span>
  <span id="cb-res" class="text-slate-400" data-mem-mb="0">—</span>
  <span id="cb-dot" class="dot-y"></span>
  <span id="cb-status">Loading...</span>
  <button onclick="openResizeDialog()" style="border:1px solid #1a3060" class="ml-auto rounded px-2 py-1 hover:bg-slate-700 text-slate-300">Resize cluster</button>
</div>

<!-- Resize modal -->
<div id="resize-modal" class="hidden fixed inset-0 bg-black/60 flex items-center justify-center z-50">
  <div style="background:#0d1b3e;border:1px solid #1a3060" class="rounded-lg p-6 w-80 shadow-xl">
    <h3 class="font-semibold mb-4 text-white">Resize Cluster</h3>
    <div class="mb-3">
      <label class="text-xs text-slate-400 block mb-1">Memory (MB)</label>
      <input type="number" id="resize-memory" value="3072" step="512" min="2048">
    </div>
    <div class="mb-4">
      <label class="text-xs text-slate-400 block mb-1">CPUs</label>
      <input type="number" id="resize-cpus" value="2" min="1" max="8">
    </div>
    <div class="flex gap-2">
      <button onclick="doResize()" class="flex-1 rounded px-3 py-2 text-sm font-semibold" style="background:#B4FF3C;color:#050d1f">Resize</button>
      <button onclick="document.getElementById('resize-modal').classList.add('hidden')" class="flex-1 bg-slate-700 hover:bg-slate-600 text-white rounded px-3 py-2 text-sm">Cancel</button>
    </div>
    <div id="resize-status" class="mt-3 text-sm"></div>
  </div>
</div>

<div class="flex flex-1" style="min-height:calc(100vh - 92px)">

<!-- sidebar -->
<aside style="background:#050d1f;border-right:1px solid #1a3060" class="w-56 p-3 overflow-y-auto" id="sidebar">
  <div class="text-xs text-slate-500 mb-2 uppercase tracking-wider">Environments</div>
  <div id="env-list"><div class="text-slate-500 text-xs">Loading...</div></div>
  <button onclick="toggleNewEnvForm()" class="mt-3 w-full text-xs rounded px-2 py-1 hover:opacity-80 font-semibold" style="color:#B4FF3C;border:1px solid #B4FF3C;background:transparent">+ New environment</button>
  <!-- New env form -->
  <div id="new-env-form" class="hidden mt-2 rounded p-3 text-xs" style="border:1px solid #1a3060">
    <div class="mb-2">
      <label class="text-slate-400 block mb-1">Env name</label>
      <input type="text" id="new-env-name" placeholder="alice" oninput="updateEnvCmd()">
    </div>
    <div class="mb-2">
      <label class="text-slate-400 block mb-1">Profile</label>
      <select id="new-env-profile" onchange="onProfileChange()">
        <option value="">Select profile...</option>
      </select>
    </div>
    <div id="sizing-banner" class="hidden rounded p-2 mb-2"></div>
    <div class="text-slate-500 mt-1 mb-1">Run in terminal:</div>
    <code id="new-env-cmd" class="block text-green-400 break-all font-mono text-xs">klight up &lt;profile&gt; --env &lt;name&gt;</code>
    <button onclick="toggleNewEnvForm()" class="mt-2 text-slate-500 hover:text-slate-300">✕ Close</button>
  </div>
</aside>

<!-- main -->
<main class="flex-1 overflow-hidden flex flex-col">

<!-- GET STARTED TAB (role-based onboarding assistant) -->
<div id="tab-start" class="hidden flex-1 overflow-y-auto p-6">
  <div class="max-w-2xl">
    <h2 class="text-xl font-bold mb-1">Get started</h2>
    <p class="text-slate-400 text-sm mb-4">We'll ask a couple of questions and point you to the right flow and commands for your role. No Kubernetes knowledge needed.</p>

    <!-- Auto-detected capabilities -->
    <div id="probe-banner" class="rounded-lg p-3 mb-5 text-xs" style="background:#0d1b3e;border:1px solid #1a3060">
      <span class="text-slate-400">Detecting your environment…</span>
    </div>

    <!-- Q0: role -->
    <div id="q-role" class="rounded-lg p-5 mb-4" style="background:#0d1b3e">
      <h3 class="font-semibold mb-3" style="color:#B4FF3C">What are you?</h3>
      <div class="grid grid-cols-1 gap-2">
        <button onclick="pickRole('dev')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
          <span class="font-medium text-white">Developer</span>
          <span class="block text-xs text-slate-400">I write code for one or more services</span>
        </button>
        <button onclick="pickRole('devops')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
          <span class="font-medium text-white">DevOps / Platform</span>
          <span class="block text-xs text-slate-400">I set up the infra and the team's central file</span>
        </button>
        <button onclick="pickRole('techlead')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
          <span class="font-medium text-white">Tech lead / Architect</span>
          <span class="block text-xs text-slate-400">I decide architecture, multiple languages (gRPC, GraphQL)</span>
        </button>
      </div>
    </div>

    <!-- Q1: follow-up (dynamic) -->
    <div id="q-follow" class="hidden rounded-lg p-5 mb-4" style="background:#0d1b3e">
      <h3 id="q-follow-title" class="font-semibold mb-3" style="color:#B4FF3C"></h3>
      <div id="q-follow-opts" class="grid grid-cols-1 gap-2"></div>
    </div>

    <!-- Result -->
    <div id="q-result" class="hidden rounded-lg p-5 mb-4" style="background:#050d1f;border:1px solid #B4FF3C">
      <h3 id="q-result-title" class="font-semibold mb-2" style="color:#B4FF3C"></h3>
      <p id="q-result-desc" class="text-sm text-slate-300 mb-3"></p>
      <div class="text-xs text-slate-400 mb-1">Run these commands:</div>
      <pre id="q-result-cmd" class="text-green-400 rounded p-3 mb-3" style="background:#020810"></pre>
      <div class="flex gap-2 flex-wrap">
        <a id="q-result-link" href="#" target="_blank" class="px-3 py-2 rounded text-sm font-semibold no-underline" style="background:#B4FF3C;color:#050d1f">Open WORKSHOP.md</a>
        <button id="q-result-goto" onclick="" class="px-3 py-2 rounded text-sm text-slate-200" style="border:1px solid #1a3060"></button>
        <button onclick="resetAssistant()" class="px-3 py-2 rounded text-sm text-slate-400" style="border:1px solid #1a3060">↺ Start over</button>
      </div>
    </div>
  </div>
</div>

<!-- ENVIRONMENTS TAB -->
<div id="tab-envs" class="hidden flex-1 flex flex-col overflow-hidden">
  <div class="flex-1 overflow-y-auto p-5" id="services-panel">
    <div class="flex flex-col items-center justify-center text-center py-8">
      <img src="/static/images/klight-sloth4.png" class="w-32 mb-4 opacity-80" alt="klight sloth">
      <p class="text-slate-400 text-sm">Select an environment from the sidebar →</p>
    </div>
    <div id="local-processes-panel" class="mt-2"></div>
  </div>
  <div id="logs-panel" class="hidden flex flex-col" style="height:320px;border-top:1px solid #1a3060;background:#020810">
    <div class="flex items-center px-4 py-2" style="border-bottom:1px solid #1a3060">
      <span class="text-xs text-slate-400" id="logs-title">Logs</span>
      <span class="ml-3 text-xs text-slate-600">↕ drag the bottom edge to resize</span>
      <button onclick="document.getElementById('logs-panel').classList.add('hidden')" class="ml-auto text-slate-500 hover:text-white text-xs">✕</button>
    </div>
    <pre class="flex-1 overflow-y-auto p-3 text-green-400" id="logs-content"></pre>
  </div>
</div>

<!-- SETUP WIZARD TAB -->
<div id="tab-setup" class="hidden flex-1 overflow-y-auto p-6">
  <div class="max-w-2xl">
    <h2 class="text-xl font-bold mb-1">Setup Wizard</h2>
    <p class="text-slate-400 text-sm mb-6">Connect your Git platform, scan repos, generate klight.yaml files, and create klight-team.yaml — without cloning any repos.</p>

    <!-- Step 1: Platform + Token -->
    <div class="rounded-lg p-5 mb-4" style="background:#0d1b3e" id="step1">
      <h3 class="font-semibold mb-3" style="color:#B4FF3C">Step 1 — Platform &amp; Access</h3>
      <div class="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label class="text-xs text-slate-400 block mb-1">Platform</label>
          <select id="s-platform">
            <option value="github">GitHub</option>
            <option value="gitlab">GitLab</option>
            <option value="bitbucket">Bitbucket</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-slate-400 block mb-1">Organization / Username</label>
          <input type="text" id="s-org" placeholder="mycompany">
        </div>
      </div>
      <div class="mb-3">
        <label class="text-xs text-slate-400 block mb-1">Token (read + write for auto-PRs)</label>
        <input type="password" id="s-token" placeholder="ghp_xxx or glpat-xxx">
      </div>
      <div class="mb-3">
        <label class="text-xs text-slate-400 block mb-1">Docker Registry prefix</label>
        <input type="text" id="s-registry" placeholder="ghcr.io/mycompany  or  123.dkr.ecr.us-east-1.amazonaws.com/co  or  registry.gitlab.com/mycompany">
        <p class="text-xs text-slate-500 mt-1">klight will set image: {registry}/{service}:main for each service</p>
      </div>
      <button onclick="scanRepos()" class="px-4 py-2 rounded text-sm font-semibold" style="background:#B4FF3C;color:#050d1f">Scan repos →</button>
      <div id="scan-status" class="mt-2 text-sm text-slate-400"></div>
    </div>

    <!-- Step 2: Repo selection -->
    <div class="rounded-lg p-5 mb-4 hidden" style="background:#0d1b3e" id="step2">
      <h3 class="font-semibold mb-3" style="color:#B4FF3C">Step 2 — Select service repos</h3>
      <div id="repo-list" class="space-y-2 mb-4 max-h-80 overflow-y-auto"></div>
      <div class="mb-3">
        <label class="text-xs text-slate-400 block mb-1">Infra / K8s repo (optional)</label>
        <input type="text" id="s-infra-repo" placeholder="company-infra (repo with existing K8s manifests)">
      </div>
      <button onclick="generateYamls()" class="px-4 py-2 rounded text-sm font-semibold" style="background:#B4FF3C;color:#050d1f">Generate klight.yaml files →</button>
    </div>

    <!-- Step 3: Review klight.yaml -->
    <div class="rounded-lg p-5 mb-4 hidden" style="background:#0d1b3e" id="step3">
      <h3 class="font-semibold mb-3" style="color:#B4FF3C">Step 3 — Review &amp; confirm klight.yaml</h3>
      <div id="yaml-review" class="space-y-4"></div>
      <button onclick="generateTeam()" class="mt-4 px-4 py-2 rounded text-sm font-semibold" style="background:#B4FF3C;color:#050d1f">Generate klight-team.yaml →</button>
    </div>

    <!-- Step 4: klight-team.yaml + distribute -->
    <div class="rounded-lg p-5 mb-4 hidden" style="background:#0d1b3e" id="step4">
      <h3 class="font-semibold mb-3" style="color:#B4FF3C">Step 4 — Distribute</h3>
      <div id="team-yaml-preview" class="mb-4"></div>
      <button onclick="createPRs()" class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded text-sm mr-2">Open PRs →</button>
      <button onclick="downloadFiles()" class="bg-slate-600 hover:bg-slate-700 text-white px-4 py-2 rounded text-sm">Download files</button>
      <div id="pr-results" class="mt-4 space-y-2"></div>
      <div id="sync-cmd" class="hidden mt-5 rounded p-4" style="background:#050d1f">
        <p class="text-xs text-slate-400 mb-2">Share this with your team:</p>
        <pre id="sync-cmd-text" class="text-green-400"></pre>
      </div>
    </div>
  </div>
</div>

<!-- ABOUT TAB -->
<div id="tab-about" class="hidden flex-1 overflow-y-auto">
  <div class="max-w-3xl mx-auto px-6 py-12">
    <!-- Hero -->
    <div class="flex flex-col items-center text-center mb-12">
      <img src="/static/images/klight-sloth.png" class="w-64 mb-8 rounded-2xl shadow-2xl" alt="klight mascot">
      <h1 class="text-3xl font-bold mb-4" style="color:#B4FF3C">klight — K8s environments for your whole team</h1>
      <p class="text-lg mb-8" style="color:#8BA3C7">Built by SlothLabs. klight gives every developer a fully isolated Kubernetes environment in minutes — no infra knowledge required.</p>
      <div class="flex gap-4 justify-center flex-wrap">
        <a href="https://slothlabs.org/klight" target="_blank"
           class="px-6 py-3 rounded-lg font-semibold text-base no-underline"
           style="background:#B4FF3C;color:#050d1f">Product Page</a>
        <a href="https://github.com/slothlabsorg/kraken-light" target="_blank"
           class="px-6 py-3 rounded-lg font-semibold text-base no-underline"
           style="border:2px solid #B4FF3C;color:#B4FF3C;background:transparent">GitHub</a>
      </div>
    </div>
    <!-- Product screenshot -->
    <div class="rounded-2xl overflow-hidden shadow-2xl" style="border:1px solid #1a3060">
      <div class="px-4 py-2 text-xs font-mono" style="background:#0d1b3e;color:#8BA3C7;border-bottom:1px solid #1a3060">klight ui — http://localhost:7700</div>
      <img src="/static/images/klight-landing.png" class="w-full block" alt="klight UI screenshot">
    </div>
    <!-- Tagline footer -->
    <div class="mt-10 text-center text-sm" style="color:#8BA3C7">
      Made with care by <span style="color:#B4FF3C">SlothLabs</span> · <a href="https://github.com/slothlabsorg/kraken-light" target="_blank" style="color:#B4FF3C" class="hover:underline">Open source on GitHub</a>
    </div>
  </div>
</div>

</main>
</div>

<script>
let scannedRepos = [];
let generatedYamls = {};
let teamYaml = '';
const _org = () => document.getElementById('s-org').value;
const _token = () => document.getElementById('s-token').value;
const _platform = () => document.getElementById('s-platform').value;
const _registry = () => document.getElementById('s-registry').value;
const _infraRepo = () => document.getElementById('s-infra-repo').value;

// Tab switching
function tab(name) {
  ['start','envs','setup','about'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
    const btn = document.getElementById('tb-' + t);
    if (t === name) {
      btn.style.background = '#B4FF3C';
      btn.style.color = '#050d1f';
      btn.className = 'px-3 py-1 rounded text-sm font-semibold';
    } else {
      btn.style.background = '';
      btn.style.color = '';
      btn.className = 'px-3 py-1 rounded text-sm text-slate-300 hover:bg-slate-700';
    }
  });
}

// Envs
let currentEnv = null;
async function loadEnvs() {
  const r = await fetch('/api/envs').then(r=>r.json()).catch(()=>[]);
  const el = document.getElementById('env-list');
  el.innerHTML = r.length ? r.map(e => `
    <div onclick="selectEnv('${e.name}')"
      class="px-2 py-2 rounded cursor-pointer mb-1 text-sm hover:bg-slate-700 ${currentEnv===e.name?'bg-slate-700':''}"
      id="env-${e.name}">
      <div class="font-medium">${e.name}</div>
      <div class="text-xs text-slate-500">${e.status}</div>
    </div>`) .join('') : '<div class="text-slate-500 text-xs">No environments</div>';
}

async function selectEnv(name) {
  currentEnv = name;
  document.querySelectorAll('[id^=env-]').forEach(el => el.classList.remove('bg-slate-700'));
  const el = document.getElementById('env-'+name);
  if (el) el.classList.add('bg-slate-700');
  await loadServices(name);
}

async function loadServices(name) {
  const panel = document.getElementById('services-panel');
  const svcs = await fetch(`/api/envs/${name}/services`).then(r=>r.json()).catch(()=>[]);
  const healthy = svcs.filter(s=>s.healthy).length;
  const cards = svcs.map(s => {
    const dot = s.healthy ? 'dot-g' : (s.status.includes('Loop') ? 'dot-r' : 'dot-y');
    return `<div
      class="rounded-lg p-4" style="background:#0d1b3e;border:1px solid #1a3060" onmouseover="this.style.borderColor='#B4FF3C'" onmouseout="this.style.borderColor='#1a3060'">
      <div class="flex items-center gap-2 mb-1 cursor-pointer" onclick="showLogs('${name}','${s.name}')">
        <span class="${dot}"></span>
        <span class="font-medium text-white">${s.name}</span>
        ${s.restarts>0 ? `<span class="text-xs bg-yellow-900 text-yellow-300 px-2 rounded">${s.restarts}×</span>` : ''}
        <span class="ml-auto text-xs text-slate-400">${s.ready}/${s.total}</span>
      </div>
      <div class="text-xs text-slate-400 cursor-pointer mb-2" onclick="showLogs('${name}','${s.name}')">${s.status}</div>
      <div class="flex items-center gap-2">
        <button onclick="rebuildService('${name}','${s.name}')" id="rebuild-btn-${s.name}" class="text-xs rounded px-2 py-1" style="border:1px solid #B4FF3C;color:#B4FF3C">🔨 Rebuild</button>
        <span id="rebuild-status-${s.name}" class="text-xs text-slate-400"></span>
      </div>
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="mb-4 flex items-center gap-3">
      <h2 class="text-lg font-semibold">${name}</h2>
      <span class="text-sm text-slate-400">${healthy}/${svcs.length} ready</span>
      <button onclick="destroyEnv('${name}')" class="ml-auto text-xs text-red-400 border border-red-800 rounded px-2 py-1 hover:bg-red-900">Destroy</button>
    </div>
    <div class="grid grid-cols-2 lg:grid-cols-3 gap-3">${cards}</div>
    <p class="mt-3 text-xs text-slate-500">Click a service card → view logs. 🔨 Rebuild = your build command → load into minikube → restart → wait for Ready.</p>
    <div id="local-processes-panel" class="mt-6"></div>`;
  loadLocalProcesses();
}

// ── Rebuild a k8s service from a local repo path (one-button dev loop) ───────
function getServicePath(svc) {
  const paths = JSON.parse(localStorage.getItem('klight_service_paths') || '{}');
  if (paths[svc]) return paths[svc];
  const p = prompt(`Local repo path for '${svc}' (must contain klight.yaml):`, `~/dev/${svc}`);
  if (!p) return null;
  paths[svc] = p;
  localStorage.setItem('klight_service_paths', JSON.stringify(paths));
  return p;
}

async function rebuildService(env, svc) {
  const path = getServicePath(svc);
  if (!path) return;
  const btn = document.getElementById(`rebuild-btn-${svc}`);
  const status = document.getElementById(`rebuild-status-${svc}`);
  btn.disabled = true;
  status.className = 'text-xs text-yellow-300';
  status.textContent = 'Building & redeploying… (can take a few min for JVM services)';
  try {
    const res = await fetch(`/api/envs/${env}/services/${svc}/rebuild`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path}),
    });
    const d = await res.json().catch(() => ({}));
    if (res.ok && d.ok) {
      status.className = 'text-xs text-green-400';
      status.textContent = `✓ Green again (${d.elapsed_seconds}s)`;
      loadServices(env);
    } else {
      status.className = 'text-xs text-red-400';
      status.textContent = '✗ ' + (d.detail || 'failed');
    }
  } catch (e) {
    status.className = 'text-xs text-red-400';
    status.textContent = '✗ ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

// ── Local dev processes (non-k8s: frontend dev servers, plugin watch, proxies) ─
async function loadLocalProcesses() {
  const panel = document.getElementById('local-processes-panel');
  if (!panel) return;
  const procs = await fetch('/api/local/processes').then(r => r.json()).catch(() => []);
  panel.innerHTML = `
    <h3 class="text-sm font-semibold text-slate-300 mb-2">Local dev processes (frontend/proxies — not k8s pods)</h3>
    <div class="space-y-2">${procs.map(p => `
      <div class="rounded-lg p-3 flex items-center gap-3" style="background:#0d1b3e;border:1px solid #1a3060">
        <span class="${p.running ? (p.port && !p.port_ok ? 'dot-y' : 'dot-g') : 'dot-r'}"></span>
        <div class="flex-1 min-w-0">
          <div class="text-sm text-white">${p.label}</div>
          ${p.log_tail ? `<div class="text-xs text-slate-500 truncate">${p.log_tail.split('\\n').pop()}</div>` : ''}
        </div>
        <button onclick="toggleLocalProcess('${p.key}', ${p.running})" class="text-xs rounded px-3 py-1 font-semibold"
          style="${p.running ? 'border:1px solid #ef4444;color:#ef4444' : 'background:#B4FF3C;color:#050d1f'}">
          ${p.running ? 'Stop' : 'Start'}
        </button>
      </div>`).join('')}
    </div>`;
}

async function toggleLocalProcess(key, isRunning) {
  await fetch(`/api/local/processes/${key}/${isRunning ? 'stop' : 'start'}`, {method: 'POST'});
  setTimeout(loadLocalProcesses, 800);
}

async function showLogs(env, svc) {
  const p = document.getElementById('logs-panel');
  p.classList.remove('hidden');
  document.getElementById('logs-title').textContent = `${svc} — ${env}`;
  document.getElementById('logs-content').textContent = 'Loading...';
  const d = await fetch(`/api/envs/${env}/services/${svc}/logs`).then(r=>r.json());
  document.getElementById('logs-content').textContent = d.logs || '(no logs)';
}

async function destroyEnv(name) {
  if (!confirm(`Destroy '${name}'? All data lost.`)) return;
  await fetch(`/api/envs/${name}`, {method:'DELETE'});
  currentEnv = null;
  await loadEnvs();
  document.getElementById('services-panel').innerHTML = '<p class="text-slate-400 text-sm">Destroyed.</p>';
}

async function newEnv() {
  const name = prompt('Environment name:');
  if (!name) return;
  alert(`Run: klight env create ${name} --with-infra`);
}

// Setup wizard
async function scanRepos() {
  const st = document.getElementById('scan-status');
  st.textContent = 'Scanning repos...';
  const r = await fetch('/api/setup/scan', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({token:_token(), org:_org(), platform:_platform()})
  }).then(r=>r.json()).catch(e=>({error:e.message}));

  if (r.error || r.detail) {
    st.textContent = 'Error: ' + (r.error || r.detail);
    return;
  }
  scannedRepos = r.repos;
  st.textContent = `Found ${r.total} repos`;
  document.getElementById('step2').classList.remove('hidden');

  const serviceRepos = r.repos.filter(r => r.is_service);
  document.getElementById('repo-list').innerHTML = serviceRepos.map(repo => `
    <label class="flex items-start gap-3 cursor-pointer hover:bg-slate-700 p-2 rounded">
      <input type="checkbox" class="repo-cb mt-1" value="${repo.name}" ${repo.has_dockerfile ? 'checked' : ''}>
      <div class="flex-1">
        <div class="font-medium text-sm flex flex-wrap items-center gap-1">${repo.name}
          ${repo.has_klight ? '<span class="text-xs text-green-400">✓ klight.yaml</span>' : '<span class="text-xs text-yellow-400">⚠ missing klight.yaml</span>'}
          ${repo.has_dockerfile ? '<span class="text-xs text-slate-400">✓ Dockerfile</span>' : ''}
          ${repo.has_deploy_folder ? '<span class="text-xs text-blue-400">✓ deploy/</span>' : ''}
          ${(repo.unknown_needs||[]).map(n => `<span class="text-xs px-1.5 py-0.5 rounded" style="background:#7c2d1220;color:#fb923c;border:1px solid #c2410c40">⚠ custom: ${n}</span>`).join('')}
        </div>
        ${repo.description ? `<div class="text-xs text-slate-500">${repo.description.substring(0,80)}</div>` : ''}
      </div>
    </label>`).join('');
}

async function generateYamls() {
  const selected = [...document.querySelectorAll('.repo-cb:checked')].map(c => c.value);
  if (!selected.length) { alert('Select at least one repo'); return; }

  const r = await fetch('/api/setup/generate', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      token:_token(), org:_org(), platform:_platform(),
      selected_repos: selected, registry:_registry(),
      infra_repo:_infraRepo(), image_tag:'main'
    })
  }).then(r=>r.json());

  document.getElementById('step3').classList.remove('hidden');

  // Catalog warning panel
  const warnings = r.catalog_warnings || [];
  let warningHtml = '';
  if (warnings.length) {
    const items = warnings.map(w =>
      `<li class="mt-1"><strong class="text-orange-300">${w.repo}</strong> needs: [${w.unknown_needs.join(', ')}] — not in built-in catalog</li>`
    ).join('');
    warningHtml = `
    <div class="rounded-lg p-4 mb-4" style="background:#1a0f00;border:1px solid #c2410c60">
      <div class="flex items-start gap-3">
        <span class="text-orange-400 text-lg mt-0.5">⚠</span>
        <div>
          <p class="font-semibold text-orange-300 text-sm mb-1">Custom infra detected</p>
          <p class="text-xs text-slate-400 mb-2">The following services declare <code>needs:</code> entries not in the built-in catalog. Add them to <code>klight-catalog.yaml</code> in your infra repo so klight knows how to start them.</p>
          <ul class="text-xs text-slate-300 list-disc list-inside">${items}</ul>
          <p class="text-xs text-slate-500 mt-2">Built-in: postgres · kafka · redis · mongodb · rabbitmq · localstack · elasticsearch<br>
          See <a href="https://github.com/slothlabsorg/kraken-light/blob/main/docs/12-custom-catalog.md" target="_blank" class="text-orange-400 underline">docs/12-custom-catalog.md</a></p>
        </div>
      </div>
    </div>`;
  }
  document.getElementById('yaml-review').innerHTML = warningHtml + r.results.map(res => `
    <div class="border border-slate-600 rounded p-3">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium text-sm">${res.repo}</span>
        <span class="text-xs ${res.status==='exists' ? 'text-green-400' : 'text-yellow-400'}">
          ${res.status === 'exists' ? '✓ already has klight.yaml' : '⚡ generated'}
        </span>
      </div>
      <textarea id="yaml-${res.repo}" class="font-mono text-xs" rows="8">${res.yaml}</textarea>
    </div>`).join('');

  generatedYamls = {};
  r.results.forEach(res => { generatedYamls[res.repo] = res.yaml; });
}

async function generateTeam() {
  // Collect edited yamls
  Object.keys(generatedYamls).forEach(repo => {
    const ta = document.getElementById(`yaml-${repo}`);
    if (ta) generatedYamls[repo] = ta.value;
  });

  const services = Object.keys(generatedYamls).map(repo => ({
    name: repo, repo_name: repo,
    url: `https://github.com/${_org()}/${repo}`
  }));

  const r = await fetch('/api/setup/team-yaml', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      org:_org(), registry:_registry(), services,
      profiles: {'all': services.map(s=>s.name)},
      infra_repo:_infraRepo(), image_tag:'main'
    })
  }).then(r=>r.json());

  teamYaml = r.yaml;
  document.getElementById('step4').classList.remove('hidden');
  document.getElementById('team-yaml-preview').innerHTML = `
    <label class="text-xs text-slate-400 block mb-1">klight-team.yaml</label>
    <textarea class="font-mono text-xs" rows="14" id="team-yaml-ta">${r.yaml}</textarea>`;
}

async function createPRs() {
  const results = document.getElementById('pr-results');
  results.innerHTML = '';
  const reposNeedingPR = Object.entries(generatedYamls)
    .filter(([repo]) => !scannedRepos.find(r=>r.name===repo && r.has_klight));

  for (const [repo, yaml] of reposNeedingPR) {
    const r = await fetch('/api/setup/create-pr', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:_token(), org:_org(), repo, yaml_content: yaml})
    }).then(r=>r.json());
    results.innerHTML += r.ok
      ? `<div class="text-green-400 text-sm">✓ ${repo}: <a href="${r.pr_url}" target="_blank" class="underline">${r.pr_url}</a></div>`
      : `<div class="text-red-400 text-sm">✗ ${repo}: ${r.error}</div>`;
  }

  // Show sync command
  const infra = _infraRepo() || 'your-infra-repo';
  const syncUrl = `https://raw.githubusercontent.com/${_org()}/${infra}/main/klight-team.yaml`;
  document.getElementById('sync-cmd').classList.remove('hidden');
  document.getElementById('sync-cmd-text').textContent = `klight sync ${syncUrl}`;
}

function downloadFiles() {
  // Download klight-team.yaml
  const ta = document.getElementById('team-yaml-ta');
  const content = ta ? ta.value : teamYaml;
  const a = document.createElement('a');
  a.href = 'data:text/yaml;charset=utf-8,' + encodeURIComponent(content);
  a.download = 'klight-team.yaml';
  a.click();

  // Download individual klight.yaml files
  Object.entries(generatedYamls).forEach(([repo, yaml]) => {
    const b = document.createElement('a');
    b.href = 'data:text/yaml;charset=utf-8,' + encodeURIComponent(yaml);
    b.download = `klight-${repo}.yaml`;
    setTimeout(() => b.click(), 200);
  });
}

// ── Cluster bar ──────────────────────────────────────────────────────────────
async function loadClusterInfo() {
  try {
    const r = await fetch('/api/local/cluster-info').then(r=>r.json());
    document.getElementById('cb-name').textContent = r.profile || '—';
    const memGb = r.memory_mb ? (r.memory_mb/1024).toFixed(1)+'GB' : '—';
    const res = r.cpus ? `${r.cpus} CPUs · ${memGb}` : '—';
    const el = document.getElementById('cb-res');
    el.textContent = res;
    el.dataset.memMb = r.memory_mb || '0';
    const dot = document.getElementById('cb-dot');
    const st = (r.status || '').toLowerCase();
    dot.className = st === 'running' ? 'dot-g' : st === 'stopped' ? 'dot-r' : 'dot-y';
    document.getElementById('cb-status').textContent = r.status || '—';
    // Pre-fill resize dialog with current values
    if (r.memory_mb) document.getElementById('resize-memory').value = r.memory_mb;
    if (r.cpus) document.getElementById('resize-cpus').value = r.cpus;
  } catch {}
}

function openResizeDialog() {
  document.getElementById('resize-modal').classList.remove('hidden');
  document.getElementById('resize-status').textContent = '';
}

function openResizeDialogWith(mb) {
  document.getElementById('resize-memory').value = mb;
  openResizeDialog();
}

async function doResize() {
  const st = document.getElementById('resize-status');
  const mb = parseInt(document.getElementById('resize-memory').value);
  const cpus = parseInt(document.getElementById('resize-cpus').value);
  const profile = document.getElementById('cb-name').textContent || 'klight-demo';
  st.className = 'mt-3 text-sm text-yellow-300';
  st.textContent = 'Resizing… this takes 1-2 min';
  try {
    const r = await fetch('/api/local/resize', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({memory_mb: mb, cpus, profile})
    }).then(r=>r.json());
    if (r.ok) {
      st.className = 'mt-3 text-sm text-green-400';
      st.textContent = `✓ Resized to ${cpus} CPUs, ${(mb/1024).toFixed(1)} GB`;
      await loadClusterInfo();
    } else {
      st.className = 'mt-3 text-sm text-red-400';
      st.textContent = 'Error: ' + (r.detail || JSON.stringify(r));
    }
  } catch (e) {
    st.className = 'mt-3 text-sm text-red-400';
    st.textContent = 'Error: ' + e.message;
  }
}

// ── New environment form ──────────────────────────────────────────────────────
let profilesCache = [];

async function toggleNewEnvForm() {
  const form = document.getElementById('new-env-form');
  const hidden = form.classList.toggle('hidden');
  if (!hidden && profilesCache.length === 0) {
    const r = await fetch('/api/local/profiles').then(r=>r.json()).catch(()=>({profiles:[]}));
    profilesCache = r.profiles || [];
    const sel = document.getElementById('new-env-profile');
    profilesCache.forEach(p => {
      sel.innerHTML += `<option value="${p}">${p}</option>`;
    });
  }
}

function updateEnvCmd() {
  const name = document.getElementById('new-env-name').value || '<name>';
  const profile = document.getElementById('new-env-profile').value || '<profile>';
  document.getElementById('new-env-cmd').textContent = `klight up ${profile} --env ${name}`;
}

async function onProfileChange() {
  updateEnvCmd();
  const profile = document.getElementById('new-env-profile').value;
  const banner = document.getElementById('sizing-banner');
  if (!profile) { banner.classList.add('hidden'); return; }
  banner.classList.remove('hidden');
  banner.className = 'rounded p-2 mb-2 text-xs bg-slate-700 text-slate-300';
  banner.textContent = 'Estimating…';
  try {
    const r = await fetch(`/api/local/sizing/${profile}`).then(r=>r.json());
    if (r.error) {
      banner.className = 'rounded p-2 mb-2 text-xs bg-slate-700 text-slate-400';
      banner.textContent = r.error;
      return;
    }
    const clusterMb = parseInt(document.getElementById('cb-res').dataset.memMb || '0');
    const estGb = (r.estimated_mb/1024).toFixed(1);
    const fits = !clusterMb || r.estimated_mb <= clusterMb;
    if (fits) {
      banner.className = 'rounded p-2 mb-2 text-xs bg-green-950 text-green-300';
      banner.textContent = `Profile '${profile}': ~${estGb} GB estimated  ✓ Fits`;
    } else {
      const recMb = r.recommended_mb;
      banner.className = 'rounded p-2 mb-2 text-xs bg-yellow-950 text-yellow-300';
      banner.innerHTML = `⚠ Profile '${profile}': ~${estGb} GB — cluster may be unstable<br>
        <button onclick="openResizeDialogWith(${recMb})" class="mt-1 underline hover:text-yellow-100">
          Resize to ${(recMb/1024).toFixed(0)} GB →
        </button>`;
    }
  } catch {
    banner.textContent = 'Could not estimate memory';
  }
}

// ── Get started assistant ─────────────────────────────────────────────────────
const REPO_BASE = 'https://github.com/slothlabsorg/klight-suite-test/blob/main/demos';
let probeData = null;

const WORKSHOPS = {
  dev:      { demo: 'dev-students',       link: REPO_BASE + '/dev-students/WORKSHOP.md' },
  devops:   { demo: 'devops-todo',        link: REPO_BASE + '/devops-todo/WORKSHOP.md' },
  techlead: { demo: 'techlead-dropship',  link: REPO_BASE + '/techlead-dropship/WORKSHOP.md' },
};

async function loadProbe() {
  const b = document.getElementById('probe-banner');
  try {
    probeData = await fetch('/api/onboarding/probe').then(r=>r.json());
  } catch { probeData = null; }
  if (!probeData) { b.innerHTML = '<span class="text-slate-400">Could not detect the environment (still works the same below).</span>'; return; }
  const chip = (ok, label) => `<span class="px-2 py-0.5 rounded mr-1" style="background:${ok?'#0f2a14':'#2a0f0f'};color:${ok?'#86efac':'#fca5a5'}">${ok?'✓':'✗'} ${label}</span>`;
  let extra = '';
  if (probeData.has_team_yaml) extra += ` <span class="text-slate-400">· team '${probeData.team_name}' (${(probeData.profiles||[]).join(', ')||'no profiles'})</span>`;
  if (probeData.active_target) extra += ` <span class="text-slate-400">· target: ${probeData.active_target}</span>`;
  b.innerHTML = '<span class="text-slate-400 mr-2">Detected:</span>' +
    chip(probeData.kubectl_access, 'kubectl access') +
    chip(probeData.local_cluster, 'local minikube') +
    chip(probeData.has_team_yaml, 'klight-team.yaml') + extra;
}

function pickRole(role) {
  const fq = document.getElementById('q-follow');
  const title = document.getElementById('q-follow-title');
  const opts = document.getElementById('q-follow-opts');
  document.getElementById('q-result').classList.add('hidden');

  if (role === 'dev') {
    title.textContent = 'Do you have the repos cloned locally?';
    opts.innerHTML = `
      <button onclick="result('dev','local')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
        <span class="font-medium text-white">Yes, I have the repos</span>
        <span class="block text-xs text-slate-400">World 1 — klight from-repos</span></button>
      <button onclick="result('dev','sync')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
        <span class="font-medium text-white">No, I have a klight-team.yaml URL</span>
        <span class="block text-xs text-slate-400">klight sync + klight up (no cloning)</span></button>`;
  } else if (role === 'devops') {
    title.textContent = 'Do you have access to a cluster?';
    opts.innerHTML = `
      <button onclick="result('devops','local')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
        <span class="font-medium text-white">Local minikube only</span>
        <span class="block text-xs text-slate-400">Setup Wizard + company-infra demo</span></button>
      <button onclick="result('devops','remote')" class="ob-opt text-left rounded px-4 py-3" style="border:1px solid #1a3060">
        <span class="font-medium text-white">Remote cluster (EKS/GKE)</span>
        <span class="block text-xs text-slate-400">klight connect + klight use remote</span></button>`;
  } else {
    // techlead: no follow-up needed
    result('techlead', 'polyglot');
    fq.classList.add('hidden');
    return;
  }
  fq.classList.remove('hidden');
}

const RESULTS = {
  'dev|local': {
    title: 'World 1 route — local development',
    desc: 'Local clones: klight builds and deploys your services in dependency order.',
    cmd: `klight local setup\nklight from-repos ./services/* --env dev\nklight open students-web --env dev`,
    role: 'dev', goto: 'envs', gotoLabel: 'View Environments',
  },
  'dev|sync': {
    title: 'Sync route — no service cloning needed',
    desc: "Point at the team's central file and bring up a whole profile.",
    cmd: `klight sync https://raw.githubusercontent.com/<org>/company-infra/main/klight-team.yaml\nklight use local\nklight up <profile> --env dev`,
    role: 'dev', goto: 'envs', gotoLabel: 'View Environments',
  },
  'devops|local': {
    title: 'Local DevOps route — create the central file',
    desc: 'Use the Setup Wizard to scan your repos and generate klight-team.yaml, then try it out with the company-infra demo.',
    cmd: `klight local setup\n# Generate klight-team.yaml with the Setup Wizard (tab above)\nklight up todo --env alice`,
    role: 'devops', goto: 'setup', gotoLabel: 'Open Setup Wizard',
  },
  'devops|remote': {
    title: 'Remote DevOps route — shared cluster',
    desc: 'Connect the remote cluster and switch target. Devs will run klight up against the cluster.',
    cmd: `klight connect --kubeconfig ~/company-dev.yaml\nklight use remote\nklight up todo --env alice`,
    role: 'devops', goto: 'setup', gotoLabel: 'Open Setup Wizard',
  },
  'techlead|polyglot': {
    title: 'Polyglot route — gRPC + GraphQL',
    desc: 'Services in different languages (Rust gRPC), a GraphQL BFF, and a custom build. klight orchestrates without touching your code.',
    cmd: `klight local setup\nklight local resize --memory 8192 --cpus 4\nklight from-repos ./services/* --env tl\nklight open dropship-web --env tl`,
    role: 'techlead', goto: 'envs', gotoLabel: 'View Environments',
  },
};

function result(role, choice) {
  const r = RESULTS[role + '|' + choice];
  if (!r) return;
  document.getElementById('q-result-title').textContent = r.title;
  document.getElementById('q-result-desc').textContent = r.desc;
  document.getElementById('q-result-cmd').textContent = r.cmd;
  const link = document.getElementById('q-result-link');
  link.href = WORKSHOPS[r.role].link;
  const goto = document.getElementById('q-result-goto');
  goto.textContent = r.gotoLabel;
  goto.onclick = () => tab(r.goto);
  document.getElementById('q-result').classList.remove('hidden');
  document.getElementById('q-result').scrollIntoView({ behavior: 'smooth' });
}

function resetAssistant() {
  document.getElementById('q-follow').classList.add('hidden');
  document.getElementById('q-result').classList.add('hidden');
  document.getElementById('q-role').scrollIntoView({ behavior: 'smooth' });
}

tab('start');
loadProbe();
loadEnvs();
loadClusterInfo();
loadLocalProcesses();
setInterval(async () => {
  await loadEnvs();
  if (currentEnv) loadServices(currentEnv);
  else loadLocalProcesses();
}, 5000);
setInterval(loadClusterInfo, 15000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7700, log_level="error")
