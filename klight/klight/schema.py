"""
klight.yaml schema — the contract between a service repo and klight.

A developer adds klight.yaml to their service repo.
klight reads it and knows how to build, deploy, and wire the service.
The developer writes the env var names their code ALREADY reads — no code changes.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

from klight import catalog as cat


@dataclass
class BuildConfig:
    """How to build the Docker image (for non-standard builds)."""
    command: str                          # e.g. "./gradlew banking:jib --image=banking:local"
    context: str = "."                   # build context directory
    tag: str = ""                        # image tag (defaults to name:local)


@dataclass
class MigrationConfig:
    command: list[str]
    version: str = "v1"


@dataclass
class NeedConfig:
    """A single infra dependency. Can be local (StatefulSet) or external (real infra)."""
    name: str
    mode: str = "local"                  # "local" -> StatefulSet, "external" -> just env vars
    overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class KlightConfig:
    """Parsed klight.yaml for a single service."""

    name: str
    port: int
    health: str = "/health"
    image: str = ""
    needs: list[NeedConfig] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    migration: Optional[MigrationConfig] = None
    build: Optional[BuildConfig] = None
    watch_paths: list[str] = field(default_factory=list)
    manifest: Optional[str] = None  # path to existing K8s manifests (kustomize overlay)
    repo_path: Optional[Path] = None

    @classmethod
    def from_file(cls, path: Path) -> "KlightConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data, repo_path=path.parent)

    @classmethod
    def from_dict(cls, data: dict, repo_path: Optional[Path] = None) -> "KlightConfig":
        needs = []
        raw_needs = data.get("needs", [])
        if isinstance(raw_needs, list):
            for item in raw_needs:
                if isinstance(item, str):
                    needs.append(NeedConfig(name=item))
                elif isinstance(item, dict):
                    name = next(iter(item))
                    cfg = item[name] or {}
                    needs.append(NeedConfig(
                        name=name,
                        mode=cfg.get("mode", "local"),
                        overrides={k: v for k, v in cfg.items() if k != "mode"},
                    ))
        elif isinstance(raw_needs, dict):
            for name, cfg in raw_needs.items():
                cfg = cfg or {}
                needs.append(NeedConfig(
                    name=name,
                    mode=cfg.get("mode", "local"),
                    overrides={k: v for k, v in cfg.items() if k != "mode"},
                ))

        migration = None
        if "migration" in data:
            m = data["migration"]
            migration = MigrationConfig(
                command=m.get("command", ["echo", "no-op"]),
                version=m.get("version", "v1"),
            )

        build = None
        if "build" in data:
            b = data["build"]
            build = BuildConfig(
                command=b.get("command", ""),
                context=b.get("context", "."),
                tag=b.get("tag", ""),
            )

        name = data["name"]
        return cls(
            name=name,
            port=int(data.get("port", 8080)),
            health=data.get("health", "/health"),
            image=data.get("image", f"{name}:local"),
            needs=needs,
            depends=data.get("depends", []),
            env=data.get("env", {}),
            migration=migration,
            build=build,
            watch_paths=data.get("watch_paths", []),
            repo_path=repo_path,
        )

    def effective_image(self) -> str:
        if self.build and self.build.tag:
            return self.build.tag
        return self.image or f"{self.name}:local"

    def sentinel_deps(self) -> str:
        deps = []
        for need in self.needs:
            if need.mode == "local" and cat.is_known(need.name):
                p = cat.port(need.name)
                deps.append(f"{need.name}:{p}")
        for d in self.depends:
            if not any(d.startswith(n.name) for n in self.needs):
                deps.append(d)
        return " ".join(deps)

    def all_provided_env(self) -> dict[str, str]:
        result = {}
        for need in self.needs:
            provided = cat.provides(need.name)
            provided.update(need.overrides)
            result.update(provided)
        return result

    def local_needs(self) -> list[NeedConfig]:
        return [n for n in self.needs if n.mode == "local"]

    def external_needs(self) -> list[NeedConfig]:
        return [n for n in self.needs if n.mode == "external"]
