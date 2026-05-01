from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, level.upper()), format=fmt)
    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
