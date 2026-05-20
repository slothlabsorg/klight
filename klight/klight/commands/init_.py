"""
klight init — scans a service repo and generates klight.yaml.
The developer only needs to answer a few questions about their service.
No K8s knowledge required.
"""

import os
import re
from pathlib import Path
import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm

app = typer.Typer(help="Generate klight.yaml for a service repo.")
console = Console()


def _detect_port(repo_path: Path) -> int:
    """Try to detect the service port from Dockerfile or common config files."""
    dockerfile = repo_path / "Dockerfile"
    if dockerfile.exists():
        text = dockerfile.read_text()
        matches = re.findall(r"EXPOSE\s+(\d+)", text)
        if matches:
            return int(matches[-1])

    # Check package.json for common port patterns
    pkg = repo_path / "package.json"
    if pkg.exists():
        text = pkg.read_text()
        m = re.search(r'"port"\s*:\s*(\d+)', text)
        if m:
            return int(m.group(1))

    return 8080


def _detect_needs(repo_path: Path) -> list[str]:
    """Detect infra dependencies from requirements.txt, package.json, build.gradle."""
    needs = []

    # Python
    req = repo_path / "requirements.txt"
    if req.exists():
        text = req.read_text().lower()
        if any(x in text for x in ["psycopg2", "sqlalchemy", "asyncpg", "aiopg"]):
            needs.append("postgres")
        if "confluent-kafka" in text or "kafka-python" in text or "aiokafka" in text:
            needs.append("kafka")
        if "redis" in text:
            needs.append("redis")
        if "boto3" in text or "aiobotocore" in text:
            needs.append("localstack")
        if "pymysql" in text or "aiomysql" in text:
            needs.append("mysql")

    # Node.js
    pkg = repo_path / "package.json"
    if pkg.exists():
        text = pkg.read_text().lower()
        if "pg" in text or "postgres" in text or "sequelize" in text:
            needs.append("postgres")
        if "kafkajs" in text or "kafka-node" in text:
            needs.append("kafka")
        if "ioredis" in text or "redis" in text:
            needs.append("redis")
        if "aws-sdk" in text or "@aws-sdk" in text:
            needs.append("localstack")

    # Gradle (Kotlin/Java Spring Boot)
    for gradle_file in ["build.gradle.kts", "build.gradle"]:
        g = repo_path / gradle_file
        if g.exists():
            text = g.read_text().lower()
            if "postgresql" in text or "spring-data-jpa" in text or "r2dbc-postgresql" in text:
                needs.append("postgres")
            if "spring-kafka" in text or "kafka" in text:
                needs.append("kafka")
            if "spring-data-redis" in text or "lettuce" in text:
                needs.append("redis")
            if "mysql" in text:
                needs.append("mysql")

    return list(dict.fromkeys(needs))  # dedupe preserving order


def _detect_health_path(repo_path: Path) -> str:
    """Guess health check path from code patterns."""
    # Spring Boot
    for gf in ["build.gradle.kts", "build.gradle"]:
        if (repo_path / gf).exists():
            return "/actuator/health"

    # Check for common health route patterns
    for pattern in ["**/main.py", "**/app.py", "**/server.js", "**/index.js"]:
        for f in repo_path.glob(pattern):
            text = f.read_text(errors="ignore")
            if "/health" in text:
                return "/health"

    return "/health"


def _detect_migration(repo_path: Path) -> dict | None:
    """Detect if there's a migration script."""
    # Python: migrate.py
    if (repo_path / "app" / "migrate.py").exists():
        return {"command": ["python", "-m", "app.migrate"]}
    if (repo_path / "migrate.py").exists():
        return {"command": ["python", "migrate.py"]}

    # Flyway / Liquibase (Java)
    for gf in ["build.gradle.kts", "build.gradle"]:
        if (repo_path / gf).exists():
            text = (repo_path / gf).read_text().lower()
            if "flyway" in text:
                return {"command": ["./gradlew", "flywayMigrate"]}
            if "liquibase" in text:
                return {"command": ["./gradlew", "liquibaseUpdate"]}

    # npm migrate scripts
    pkg = repo_path / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text())
            scripts = data.get("scripts", {})
            if "migrate" in scripts:
                return {"command": ["npm", "run", "migrate"]}
        except Exception:
            pass

    return None


@app.command()
def cmd(
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to the service repo (default: current directory)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Use detected defaults without prompting"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing klight.yaml"),
) -> None:
    """Scan a service repo and generate klight.yaml. No K8s knowledge required."""
    repo = path.resolve()

    if not repo.exists():
        console.print(f"[red]Path not found:[/red] {repo}")
        raise typer.Exit(1)

    output = repo / "klight.yaml"
    if output.exists() and not force:
        console.print(f"[yellow]klight.yaml already exists at {output}[/yellow]")
        console.print("Use --force to overwrite.")
        raise typer.Exit(0)

    console.print(f"\n[bold]Scanning[/bold] {repo.name}/\n")

    # Auto-detect
    detected_name = repo.name
    detected_port = _detect_port(repo)
    detected_needs = _detect_needs(repo)
    detected_health = _detect_health_path(repo)
    detected_migration = _detect_migration(repo)

    console.print(f"  Detected name:   [cyan]{detected_name}[/cyan]")
    console.print(f"  Detected port:   [cyan]{detected_port}[/cyan]")
    console.print(f"  Detected needs:  [cyan]{detected_needs or 'none'}[/cyan]")
    console.print(f"  Detected health: [cyan]{detected_health}[/cyan]")
    console.print(f"  Migration:       [cyan]{'yes' if detected_migration else 'no'}[/cyan]")
    console.print()

    if yes:
        name, port, needs, health = detected_name, detected_port, detected_needs, detected_health
        migration = detected_migration
        depends_raw = ""
    else:
        name = Prompt.ask("Service name", default=detected_name)
        port = int(Prompt.ask("Port", default=str(detected_port)))
        health = Prompt.ask("Health check path", default=detected_health)

        needs_str = Prompt.ask(
            "Needs (space-separated: postgres kafka redis localstack mysql)",
            default=" ".join(detected_needs) if detected_needs else "",
        )
        needs = [n.strip() for n in needs_str.split() if n.strip()] if needs_str.strip() else []

        depends_raw = Prompt.ask(
            "Depends on (space-separated: service-name:port/path or service-name:port)",
            default="",
        )

        if detected_migration and Confirm.ask("Run migrations before starting?", default=True):
            migration = detected_migration
        else:
            migration = None

    depends = [d.strip() for d in depends_raw.split() if d.strip()] if depends_raw else []

    # Build env vars section with sensible defaults based on detected needs
    env = _build_env_defaults(name, needs, depends)

    # Let the user add/override env vars interactively
    if not yes:
        console.print("\n[dim]Env vars klight will inject (your code reads these names):[/dim]")
        for k, v in env.items():
            console.print(f"  {k}={v}")
        more = Prompt.ask(
            "\nAdd more env vars? (KEY=VALUE KEY=VALUE or empty to skip)",
            default="",
        )
        if more.strip():
            for kv in more.split():
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    env[k.strip()] = v.strip()

    # Write klight.yaml
    lines = [
        f"name: {name}",
        f"port: {port}",
        f"health: {health}",
        f"image: {name}:local",
        "",
    ]

    if needs:
        lines.append(f"needs: [{', '.join(needs)}]")

    if depends:
        lines.append("depends:")
        for d in depends:
            lines.append(f"  - {d}")

    if migration:
        lines.append("migration:")
        cmd_str = ", ".join(f'"{c}"' for c in migration["command"])
        lines.append(f"  command: [{cmd_str}]")

    if env:
        lines.append("")
        lines.append("env:")
        for k, v in env.items():
            lines.append(f"  {k}: {v}")

    content = "\n".join(lines) + "\n"
    output.write_text(content)

    console.print(f"\n[bold green]✓ Generated:[/bold green] {output}")
    console.print(f"\nNext: [cyan]klight up --from-repos {repo} --env alice[/cyan]")


def _build_env_defaults(name: str, needs: list[str], depends: list[str]) -> dict[str, str]:
    """Build sensible default env vars based on declared needs."""
    env = {}
    db_name = f"{name.replace('-', '_')}_db"

    if "postgres" in needs:
        env["DB_HOST"] = "postgres"
        env["DB_PORT"] = "5432"
        env["DB_NAME"] = db_name
        env["DB_USER"] = "klight"

    if "mysql" in needs:
        env["DB_HOST"] = "mysql"
        env["DB_PORT"] = "3306"
        env["DB_NAME"] = db_name

    if "kafka" in needs:
        env["KAFKA_BOOTSTRAP_SERVERS"] = "kafka:9092"

    if "redis" in needs:
        env["REDIS_HOST"] = "redis"
        env["REDIS_PORT"] = "6379"

    if "localstack" in needs:
        env["AWS_ENDPOINT_URL"] = "http://localstack:4566"
        env["AWS_DEFAULT_REGION"] = "us-east-1"
        env["AWS_ACCESS_KEY_ID"] = "test"
        env["AWS_SECRET_ACCESS_KEY"] = "test"

    # Add URLs for service dependencies
    for dep in depends:
        svc_name = dep.split(":")[0]
        port_part = dep.split(":")[1] if ":" in dep else "8080"
        port = port_part.split("/")[0]
        env_key = f"{svc_name.upper().replace('-', '_')}_URL"
        env[env_key] = f"http://{svc_name}:{port}"

    return env
