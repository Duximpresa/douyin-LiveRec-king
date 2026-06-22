"""Central logging configuration for rotating file and GUI log consumers."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .utils.paths import resolve_app_path

LOGGER_NAME = "douyin_live_rec_king"


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(logger.level)
        return logger

    log_path = resolve_app_path("logs/app.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
