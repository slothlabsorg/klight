"""
klight setup / klight wizard — interactive setup for the team responsible.

Connects to GitHub/GitLab/Bitbucket, lists repos, scans K8s manifests,
generates klight.yaml for each service, creates profiles, and produces
klight-team.yaml + optionally opens PRs.
"""

import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Optional
import yaml
import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box

app = typer.Typer(help="Interactive setup wizard for the team responsible.")
console = Console()


# ─── Platform adapters ────────────────────────────────────────────────────────

class GitHubAdapter:
    def __init__(self, token: str, org: str):
        self.token = token
        self.org = org

    def list_repos(self) -> list[dict]:
        import urllib.request, json
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}
        url = f"https://api.github.com/orgs/{self.org}/repos?per_page=100&sort=updated"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def get_file(self, repo: str, path: str) -> Optional[str]:
        import urllib.request, json, base64
        url = f"https://api.github.com/repos/{self.org}/{repo}/contents/{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json"
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return base64.b64decode(data["content"]).decode("utf-8")
        except Exception:
            return None

    def create_pr(self, repo: str, branch: str, files: dict[str, str], title: str, body: str) -> Optional[str]:
        """Create a PR with files on a new branch. Returns PR URL or None."""
        try:
            import urllib.request, json, base64
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            }

            def api(method: str, path: str, data=None):
                url = f"https://api.github.com{path}"
                body_bytes = json.dumps(data).encode() if data else None
                req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read())

            # Get default branch SHA
            repo_info = api("GET", f"/repos/{self.org}/{repo}")
            default_branch = repo_info["default_branch"]
            ref_info = api("GET", f"/repos/{self.org}/{repo}/git/ref/heads/{default_branch}")
            sha = ref_info["object"]["sha"]

            # Create branch
            api("POST", f"/repos/{self.org}/{repo}/git/refs", {
                "ref": f"refs/heads/{branch}",
                "sha": sha,
            })

            # Commit files
            for file_path, content in files.items():
                api("PUT", f"/repos/{self.org}/{repo}/contents/{file_path}", {
                    "message": f"Add {file_path} via klight setup",
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": branch,
                })

            # Create PR
            pr = api("POST", f"/repos/{self.org}/{repo}/pulls", {
                "title": title,
                "body": body,
                "head": branch,
                "base": default_branch,
            })
            return pr["html_url"]
        except Exception as e:
            console.print(f"[yellow]PR creation failed for {repo}: {e}[/yellow]")
            return None

    def clone_repo(self, repo: str, dest: Path) -> bool:
        result = subprocess.run(
            ["git", "clone", f"https://{self.token}@github.com/{self.org}/{repo}.git", str(dest)],
            capture_output=True,
        )
        return result.returncode == 0


def _get_platform_adapter(platform: str, token: str, org: str):
    if platform == "GitHub":
        return GitHubAdapter(token, org)
    console.print(f"[yellow]{platform} not yet fully implemented — using GitHub adapter[/yellow]")
    return GitHubAdapter(token, org)


# ─── klight.yaml generation from scan ─────────────────────────────────────────

def _generate_klight_yaml(svc_name: str, scanned, ci_images: dict, repo_name: str) -> str:
    from klight.commands.init_ import _build_env_defaults
    from klight import catalog as cat

    port = scanned.port if scanned and scanned.port else 8080
    health = (scanned.health if scanned and scanned.health else "/health")
    image = ci_images.get(repo_name, ci_images.get(svc_name, f"{svc_name}:local"))
    needs = (scanned.needs if scanned and scanned.needs else [])
    manifest = scanned.manifest_path if scanned and scanned.manifest_path else ""

    # Build env: auto-provided by needs + service-specific from ConfigMaps
    env = {}
    if scanned:
        for key, value in scanned.env.items():
            # Skip if it's an auto-provided key from a need
            auto_provided = set()
            for need in needs:
                auto_provided.update(cat.provides(need).keys())
            if key not in auto_provided:
                env[key] = value

    lines = [
        "# yaml-language-server: $schema=https://slothlabsorg.github.io/klight/schema/klight.yaml.json",
        f"name: {svc_name}",
        f"port: {port}",
        f"health: {health}",
        f"image: {image}",
        "",
    ]
    if needs:
        lines.append(f"needs: [{', '.join(needs)}]")
    if manifest:
        rel_manifest = manifest
        lines.append(f"manifest: {rel_manifest}")
    if scanned and scanned.has_migration:
        lines.extend([
            "migration:",
            "  command: [\"npm\", \"run\", \"migrate\"]  # adjust for your stack",
        ])
    if env:
        lines.append("")
        lines.append("env:")
        for k, v in env.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines) + "\n"


# ─── Main wizard ──────────────────────────────────────────────────────────────

@app.command()
def cmd(
    token: str = typer.Option("", "--token", "-t", help="Platform token (read+write for PRs)", envvar="KLIGHT_SETUP_TOKEN"),
    org: str = typer.Option("", "--org", "-o", help="Organization or username"),
    platform: str = typer.Option("", "--platform", "-p", help="Platform: GitHub, GitLab, Bitbucket"),
    infra_repo: str = typer.Option("", "--infra-repo", help="Infra repo name (skip detection)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-confirm all prompts"),
) -> None:
    """
    Interactive setup wizard. Lists your repos, scans K8s manifests,
    generates klight.yaml for each service, creates klight-team.yaml.

    Example:
      klight setup --token ghp_xxx --org mycompany
    """
    console.print("\n[bold]klight setup wizard[/bold]\n")

    # Step 1 — Platform
    if not platform:
        platform = Prompt.ask(
            "Platform",
            choices=["GitHub", "GitLab", "Bitbucket", "Other"],
            default="GitHub",
        )
    if not token:
        token = Prompt.ask("Token (read + write for auto-PRs)")
    if not org:
        org = Prompt.ask("Organization or username")

    adapter = _get_platform_adapter(platform, token, org)

    # Step 2 — List repos
    console.print(f"\nFetching repos from {org}...")
    try:
        repos = adapter.list_repos()
    except Exception as e:
        console.print(f"[red]Failed to list repos: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"Found {len(repos)} repos\n")

    # Filter: repos likely to be services (have Dockerfile, not docs/scripts)
    service_repos = []
    infra_repo_name = infra_repo
    for repo in repos[:50]:  # limit to 50
        name = repo["name"]
        # Quick heuristic: check for Dockerfile via API
        has_dockerfile = bool(adapter.get_file(name, "Dockerfile"))
        has_klight = bool(adapter.get_file(name, "klight.yaml"))
        has_k8s = bool(adapter.get_file(name, "deploy") or adapter.get_file(name, "k8s") or
                       adapter.get_file(name, "manifests/README.md"))

        if has_k8s and not infra_repo_name:
            console.print(f"  [dim]Possible infra repo: {name}[/dim]")

        if has_dockerfile or has_klight:
            service_repos.append({
                "name": name,
                "has_klight": has_klight,
                "has_dockerfile": has_dockerfile,
                "description": repo.get("description", ""),
            })

    if not service_repos:
        console.print("[yellow]No service repos detected automatically.[/yellow]")
        console.print("Check your token permissions and try again.")
        raise typer.Exit(1)

    # Show selection table
    table = Table(box=box.ROUNDED, title="Detected service repos")
    table.add_column("Repo", style="cyan")
    table.add_column("klight.yaml")
    table.add_column("Dockerfile")
    table.add_column("Description")
    for r in service_repos:
        table.add_row(
            r["name"],
            "✓" if r["has_klight"] else "⚠ missing",
            "✓" if r["has_dockerfile"] else "—",
            (r["description"] or "")[:50],
        )
    console.print(table)

    if not yes:
        console.print("\nNote: Only services with Dockerfile or klight.yaml shown above.")
        proceed = Confirm.ask("Use these repos? (you can add/remove)", default=True)
        if not proceed:
            console.print("Edit the repo selection and re-run.")
            raise typer.Exit(0)

    # Step 3 — Infra repo
    if not infra_repo_name:
        infra_repo_name = Prompt.ask(
            "\nInfra/K8s repo name (leave empty if manifests are in service repos)",
            default="",
        )

    # Step 4 — Scan infra repo (if any)
    scanned_by_service: dict = {}
    ci_images: dict[str, str] = {}

    if infra_repo_name:
        console.print(f"\nScanning {infra_repo_name} for K8s manifests...")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            if adapter.clone_repo(infra_repo_name, tmp_path):
                from klight.scanner import scan_directory, scan_ci_files
                scan_result = scan_directory(tmp_path)
                for svc_name, svc in scan_result.services.items():
                    scanned_by_service[svc_name] = svc
                console.print(f"  Found {len(scan_result.services)} services, "
                               f"{len(scan_result.infra_detected)} infra components")

    # Step 5 — Generate klight.yaml for repos missing it
    repos_needing_klight = [r for r in service_repos if not r["has_klight"]]
    generated: dict[str, str] = {}  # repo_name → klight.yaml content

    if repos_needing_klight:
        console.print(f"\n[bold]Generating klight.yaml for {len(repos_needing_klight)} repos:[/bold]")
        for repo_info in repos_needing_klight:
            rname = repo_info["name"]
            scanned = scanned_by_service.get(rname)

            # Try to get CI image
            repo_ci = {}
            if infra_repo_name:
                pass  # already scanned above
            repo_ci.update(ci_images)

            yaml_content = _generate_klight_yaml(rname, scanned, repo_ci, rname)
            console.print(f"\n  [cyan]{rname}[/cyan]")
            console.print(textwrap.indent(yaml_content, "    "))

            if yes or Confirm.ask(f"  Use this klight.yaml for {rname}?", default=True):
                generated[rname] = yaml_content

    # Step 6 — Profiles
    console.print("\n[bold]Define profiles:[/bold]")
    all_service_names = [r["name"] for r in service_repos]
    profiles: dict[str, list[str]] = {}

    if yes:
        profiles["all"] = all_service_names
    else:
        console.print(f"Services: {', '.join(all_service_names)}")
        console.print("(Leave empty to skip profiles, you can add them to klight-team.yaml later)")
        while True:
            pname = Prompt.ask("Profile name (or empty to finish)", default="")
            if not pname:
                break
            svcs = Prompt.ask(f"Services in '{pname}' (space-separated)")
            profiles[pname] = [s.strip() for s in svcs.split() if s.strip()]

    # Step 7 — Generate klight-team.yaml
    team_name = org.lower().replace(" ", "-")
    team_data = {
        "version": "1",
        "team": team_name,
        "source": {
            "type": "git",
            "url": f"https://github.com/{org}/{infra_repo_name or service_repos[0]['name']}",
            "branch": "main",
        },
        "targets": {"local": "klight-demo", "remote": ""},
        "services": [
            {"name": r["name"], "image": f"ghcr.io/{org}/{r['name']}:main",
             "repo": f"https://github.com/{org}/{r['name']}"}
            for r in service_repos
        ],
        "profiles": profiles,
    }
    team_yaml = yaml.dump(team_data, default_flow_style=False, allow_unicode=True)

    console.print("\n[bold]klight-team.yaml preview:[/bold]")
    console.print(team_yaml[:800] + ("..." if len(team_yaml) > 800 else ""))

    # Step 8 — Output: PRs or download
    if generated:
        action = Prompt.ask(
            "\nHow to distribute klight.yaml files?",
            choices=["prs", "download"],
            default="prs",
        )

        if action == "prs":
            console.print("\nOpening PRs...")
            for repo_name, content in generated.items():
                url = adapter.create_pr(
                    repo_name,
                    branch="klight/add-klight-yaml",
                    files={"klight.yaml": content},
                    title="Add klight.yaml for environment management",
                    body="Generated by `klight setup`. Review and merge to enable klight for this service.\n\nSee [klight docs](https://klight.dev) for more info.",
                )
                if url:
                    console.print(f"  [green]✓[/green] {repo_name}: {url}")
                else:
                    console.print(f"  [yellow]⚠[/yellow] {repo_name}: saved locally")
                    Path(f"klight-{repo_name}.yaml").write_text(content)
        else:
            for repo_name, content in generated.items():
                out = Path(f"klight-{repo_name}.yaml")
                out.write_text(content)
                console.print(f"  [green]✓[/green] {repo_name}: saved to {out}")

    # Save klight-team.yaml
    team_file = Path("klight-team.yaml")
    team_file.write_text(team_yaml)
    console.print(f"\n[green]✓[/green] klight-team.yaml saved")

    # Final instructions
    console.print(f"""
[bold green]Setup complete![/bold green]

Commit klight-team.yaml to your infra repo, then share with your team:

  [cyan]klight sync https://raw.githubusercontent.com/{org}/{infra_repo_name or 'your-infra-repo'}/main/klight-team.yaml[/cyan]

After sync, devs run:
  [cyan]klight use local[/cyan]
  [cyan]klight up {list(profiles.keys())[0] if profiles else 'all'} --env alice[/cyan]
""")
