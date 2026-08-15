"""Startup wiring for Carrier Master DPAPI credential store."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.core.config import settings

from .file_store import DpapiCredentialStore
from .resolver import configure_credential_store

log = logging.getLogger(__name__)

_DEFAULT_WIN_ROOT = Path(r"C:\PZ-secrets\carriers")


def bootstrap_credential_store() -> bool:
    """
    Configure process-wide DpapiCredentialStore when root is usable.

    Returns True if store configured. Never raises into lifespan caller —
    caller should still wrap. ACL failure → store NOT configured (fail closed
    for migrated identities).
    """
    root = settings.carrier_credential_store_root
    if root is None and sys.platform == "win32":
        # Only auto-select default when directory already exists (operator-provisioned).
        if _DEFAULT_WIN_ROOT.is_dir():
            root = _DEFAULT_WIN_ROOT
    if root is None:
        log.info("carrier_credential_store: not configured (no root)")
        return False

    root = Path(root)
    try:
        store = DpapiCredentialStore(
            root,
            enforce_acl=bool(settings.carrier_credential_enforce_acl),
            harden_on_init=bool(settings.carrier_credential_harden_acl_on_start),
        )
    except Exception as exc:
        log.error(
            "carrier_credential_store: bootstrap refused type=%s",
            type(exc).__name__,
        )
        configure_credential_store(None)
        return False

    configure_credential_store(store)
    log.info("carrier_credential_store: configured root=%s", root)
    return True
