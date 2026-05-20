"""
klight catalog — loads infra definitions from klight-catalog.yaml.

Search order:
  1. ./klight-catalog.yaml (project-local, versionable)
  2. ~/.klight/catalog.yaml (user-global additions)
  3. Built-in defaults (this file)

Users add custom infra without touching klight's source code.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml


# Built-in defaults — always available even without a catalog file.
# The full catalog lives in klight-catalog.yaml at the repo root.
_BUILTIN: dict[str, dict[str, Any]] = {
    "postgres": {
        "description": "PostgreSQL 16",
        "image": "postgres:16-alpine",
        "port": 5432,
        "manifest": "infrastructure/postgres/base",
        "provides": {
            "GLOBAL_POSTGRES_HOST": "postgres",
            "GLOBAL_POSTGRES_PORT": "5432",
        },
    },
    "mysql": {
        "description": "MySQL 8",
        "image": "mysql:8.0",
        "port": 3306,
        "manifest": "infrastructure/mysql/base",
        "provides": {
            "GLOBAL_MYSQL_HOST": "mysql",
            "GLOBAL_MYSQL_PORT": "3306",
        },
    },
    "redis": {
        "description": "Redis 7",
        "image": "redis:7-alpine",
        "port": 6379,
        "manifest": "infrastructure/redis/base",
        "provides": {
            "GLOBAL_REDIS_HOST": "redis",
            "GLOBAL_REDIS_PORT": "6379",
        },
    },
    "mongodb": {
        "description": "MongoDB 7",
        "image": "mongo:7-jammy",
        "port": 27017,
        "manifest": "infrastructure/mongodb/base",
        "provides": {
            "GLOBAL_MONGO_URI": "mongodb://mongodb:27017",
        },
    },
    "kafka": {
        "description": "Apache Kafka 3.7 (KRaft)",
        "image": "apache/kafka:3.7.0",
        "port": 9092,
        "manifest": "infrastructure/kafka/base",
        "provides": {
            "GLOBAL_KAFKA_BOOTSTRAP": "kafka:9092",
        },
    },
    "rabbitmq": {
        "description": "RabbitMQ 3",
        "image": "rabbitmq:3-management-alpine",
        "port": 5672,
        "manifest": "infrastructure/rabbitmq/base",
        "provides": {
            "GLOBAL_RABBITMQ_URL": "amqp://guest:guest@rabbitmq:5672",
        },
    },
    "localstack": {
        "description": "LocalStack 3 — AWS emulator (S3, SQS, DynamoDB, SNS)",
        "image": "localstack/localstack:3",
        "port": 4566,
        "manifest": "infrastructure/localstack/base",
        "provides": {
            "GLOBAL_AWS_ENDPOINT": "http://localstack:4566",
            "GLOBAL_AWS_REGION": "us-east-1",
            "GLOBAL_AWS_ACCESS_KEY_ID": "test",
            "GLOBAL_AWS_SECRET_ACCESS_KEY": "test",
        },
    },
    "elasticsearch": {
        "description": "Elasticsearch 8",
        "image": "elasticsearch:8.13.0",
        "port": 9200,
        "manifest": "infrastructure/elasticsearch/base",
        "provides": {
            "GLOBAL_ELASTICSEARCH_URL": "http://elasticsearch:9200",
        },
    },
    "ollama": {
        "description": "Ollama — run LLMs locally",
        "image": "ollama/ollama:latest",
        "port": 11434,
        "manifest": "infrastructure/ollama/base",
        "provides": {
            "GLOBAL_OLLAMA_URL": "http://ollama:11434",
        },
    },
    "chromadb": {
        "description": "ChromaDB — vector database",
        "image": "chromadb/chroma:0.5.3",
        "port": 8000,
        "manifest": "infrastructure/chromadb/base",
        "provides": {
            "GLOBAL_CHROMA_URL": "http://chromadb:8000",
        },
    },
    "vault": {
        "description": "HashiCorp Vault (dev mode)",
        "image": "hashicorp/vault:1.17",
        "port": 8200,
        "manifest": "infrastructure/vault/base",
        "provides": {
            "GLOBAL_VAULT_ADDR": "http://vault:8200",
            "GLOBAL_VAULT_TOKEN": "dev-root-token",
        },
    },
}


def _load_yaml_catalog(path: Path) -> dict[str, dict]:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data.get("infra", {}) if data else {}
    except Exception:
        return {}


def load() -> dict[str, dict[str, Any]]:
    """
    Load the merged catalog: built-ins + project file + user file.
    Later entries override earlier ones (user > project > built-in).
    """
    catalog = dict(_BUILTIN)

    # Project-local catalog (./klight-catalog.yaml)
    project_path = Path(os.environ.get("KLIGHT_MANIFESTS_DIR", ".")).parent / "klight-catalog.yaml"
    if not project_path.exists():
        project_path = Path("klight-catalog.yaml")
    if project_path.exists():
        catalog.update(_load_yaml_catalog(project_path))

    # User-global catalog (~/.klight/catalog.yaml)
    user_path = Path.home() / ".klight" / "catalog.yaml"
    if user_path.exists():
        catalog.update(_load_yaml_catalog(user_path))

    return catalog


def get(name: str) -> dict[str, Any] | None:
    return load().get(name)


def image(name: str) -> str:
    entry = get(name)
    return entry["image"] if entry else f"{name}:latest"


def port(name: str) -> int:
    entry = get(name)
    return entry.get("port", 8080) if entry else 8080


def provides(name: str) -> dict[str, str]:
    entry = get(name)
    return entry.get("provides", {}) if entry else {}


def manifest_dir(name: str) -> str:
    entry = get(name)
    return entry.get("manifest", f"infrastructure/{name}/base") if entry else f"infrastructure/{name}/base"


def all_names() -> list[str]:
    return sorted(load().keys())


def is_known(name: str) -> bool:
    return name in load()
