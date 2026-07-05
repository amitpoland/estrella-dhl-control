from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, level.upper()), format=fmt)
    # HTTP access log — EXPLICITLY INFO (infra health pass d67d3722 finding
    # #4). This line used to silence uvicorn.access to WARNING, and because
    # configure_logging runs at app import — AFTER uvicorn's own dictConfig —
    # the silencer always won: production had ZERO per-request evidence, and
    # the NSSM --access-log flag could not override it (proven by local
    # truth-table boots, PROJECT_STATE DECISIONS "infra hardening #4"). The
    # gap already cost the campaign once: the atlas retirement decision is
    # parked on "is /dashboard/atlas ever hit", unanswerable without this.
    # NSSM's 10MB online rotation absorbs the stream; no NSSM change needed.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
