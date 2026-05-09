"""Helpers de path e estrutura de diretórios do Dream Squad."""

from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).parent.parent.parent


def client_dir(client_id: str) -> Path:
    return ROOT / "clients" / client_id


def execution_dir(client_id: str, timestamp: str | None = None) -> Path:
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return client_dir(client_id) / "executions" / timestamp


def load_profile(client_id: str) -> dict:
    import yaml
    path = client_dir(client_id) / "profile.yaml"
    if not path.exists():
        raise FileNotFoundError(f"profile.yaml não encontrado: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
