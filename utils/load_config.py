import yaml
from typing import Any
from pathlib import Path
from utils.log import get_logger

logger = get_logger(__name__)

def _load_client_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        logger.error("Configuration file not found: %s", config_path)
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    services = data.get("services", {}) if isinstance(data, dict) else {}
    client_cfg = services.get("client", {}) if isinstance(services, dict) else {}
    return client_cfg if isinstance(client_cfg, dict) else {}

def _load_logging_config(service_config: dict[str, Any]) -> dict[str, Any]:
    log_config = {
        "log_level": service_config.get("log_level", "info"),
        "log_file": service_config.get("log_file", None),
        "log_max_mb": service_config.get("log_max_mb", 10),
        "log_backups": service_config.get("log_backups", 5),
    }
    return log_config