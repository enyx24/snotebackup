import argparse
from pathlib import Path
from typing import Any
import yaml

from utils.log import get_logger, setup_logging
from utils.load_config import _load_client_config, _load_logging_config

def main():
    parser = argparse.ArgumentParser(description="Snote Backup Client")
    parser.add_argument("--config", help="Path to the configuration file", default="config/services.yaml")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--backup-only", action="store_true", help="Run in backup-only mode (no server)")

    args = parser.parse_args()

    client_cfg = _load_client_config(args.config)
    logging_cfg = _load_logging_config(client_cfg)
    
    setup_logging(
        level=logging_cfg["log_level"],
        log_file=logging_cfg["log_file"],
        max_mb=logging_cfg["log_max_mb"],
        backup_count=logging_cfg["log_backups"],
        force=True,
    )
    logger = get_logger(__name__)

    logger.info("Starting Snote Backup Client with configuration: %s", client_cfg)
    logger.debug("Verbose mode enabled")
    if args.backup_only:
        logger.info("Running in backup-only mode")
        pass
    else:
        logger.info("Running in full client mode")
        pass


if __name__ == "__main__":
    main()