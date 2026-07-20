"""Logging setup with rich console output."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from ..config import Settings

console = Console()


def setup_logging(settings: Settings) -> None:
    """Configure root logger with rich console + optional file handler."""
    level = getattr(logging, settings.log_level, logging.INFO)

    handlers: list[logging.Handler] = [
        RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            show_time=True,
            markup=True,
        )
    ]
    if settings.log_file:
        handlers.append(
            logging.FileHandler(settings.log_file, encoding="utf-8")
        )

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
        force=True,
    )
    # Tame some chatty libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


__all__ = ["setup_logging", "console"]
