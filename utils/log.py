import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

from config.constants import _DEFAULT_FORMAT

LogLevel = Literal["info", "debug"]


class CustomLogger:
    def __init__(self) -> None:
        self._configured = False
        self._level: LogLevel = "info"

    @staticmethod
    def _normalize_level(level: str) -> LogLevel:
        normalized = level.lower().strip()
        if normalized not in {"info", "debug"}:
            raise ValueError("level must be 'info' or 'debug'")
        return normalized

    def setup(
        self,
        level: LogLevel = "info",
        log_file: str | None = None,
        max_mb: int = 10,
        backup_count: int = 5,
        force: bool = False,
    ) -> None:
        normalized = self._normalize_level(level)
        self._level = normalized

        root = logging.getLogger()
        root.setLevel(logging.DEBUG if normalized == "debug" else logging.INFO)

        if self._configured and not force:
            return

        root.handlers.clear()
        formatter = logging.Formatter(_DEFAULT_FORMAT)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

        if log_file:
            if max_mb <= 0:
                raise ValueError("max_mb must be > 0")
            if backup_count < 1:
                raise ValueError("backup_count must be >= 1")

            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_mb * 1024 * 1024,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

        self._configured = True

    def get_logger(self, name: str | None = None) -> logging.Logger:
        return logging.getLogger(name)

    def set_debug(self, enabled: bool = True) -> None:
        self.setup("debug" if enabled else "info")

    @property
    def level(self) -> LogLevel:
        return self._level


LOGGER = CustomLogger()


def setup_logging(
    level: LogLevel = "info",
    log_file: str | None = None,
    max_mb: int = 10,
    backup_count: int = 5,
    force: bool = False,
) -> None:
    LOGGER.setup(
        level=level,
        log_file=log_file,
        max_mb=max_mb,
        backup_count=backup_count,
        force=force,
    )


def get_logger(name: str | None = None) -> logging.Logger:
    return LOGGER.get_logger(name)


def set_debug(enabled: bool = True) -> None:
    LOGGER.set_debug(enabled)


