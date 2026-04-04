from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def load_yaml_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists() or not config_path.is_file():
        return {}

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for --config support. Install with: pip install pyyaml") from exc

    with config_path.open("r", encoding="utf-8") as source:
        data = yaml.safe_load(source) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Invalid config format in {config_path}: root must be a mapping")
    return data


def get_service_config(config: Dict[str, Any], service_name: str) -> Dict[str, Any]:
    services = config.get("services")
    if not isinstance(services, dict):
        return {}

    section = services.get(service_name)
    if not isinstance(section, dict):
        return {}
    return section
