from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Cookie, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import settings

_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    key: Optional[str] = Security(_header),
    pz_session: Optional[str] = Cookie(default=None),
) -> None:
    if not settings.api_key:
        if settings.environment == "prod":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server misconfiguration: API_KEY is not configured.",
            )
        return  # dev only — auth disabled

    if key is not None and hmac.compare_digest(key, settings.api_key):
        return

    if pz_session:
        from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
        user = get_current_user_optional(pz_session=pz_session)
        if user is not None:
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


# Read-only roles that must NOT perform privileged actions (documentation).
_READ_ONLY_ROLES = frozenset({"viewer", "auditor", "master_viewer"})

# Write-capable roles permitted to perform privileged (write / execute / admin)
# actions via a SESSION. Allowlist = fail-closed: read-only roles, a missing /
# empty role, and any unknown role are ALL denied. Closes H-R5 (#502): bare
# require_api_key accepted ANY approved session (incl. read-only) on admin /
# runtime-flags / execute / debug-mutation routes.
# (X-API-Key automation is admin-equivalent and bypasses this role check.)
_WRITE_CAPABLE_ROLES = frozenset(
    {"admin", "accounts", "logistics", "master_admin", "master_editor"}
)


def require_api_key_privileged(
    key: Optional[str] = Security(_header),
    pz_session: Optional[str] = Cookie(default=None),
) -> None:
    """Auth guard for privileged actions (mutations / executions / kill-switches).

    Identical to ``require_api_key`` EXCEPT that session (cookie) callers must
    hold a write-capable role: read-only roles (viewer / auditor / master_viewer)
    are rejected with 403. The trusted X-API-Key automation path is preserved
    unchanged, as is PR #488's fail-closed behaviour (503 in prod when API_KEY
    is unset). No second auth layer — this reuses the same key + session checks.
    """
    if not settings.api_key:
        if settings.environment == "prod":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server misconfiguration: API_KEY is not configured.",
            )
        return  # dev only — auth disabled

    # Trusted automation: a valid X-API-Key is admin-equivalent.
    if key is not None and hmac.compare_digest(key, settings.api_key):
        return

    # Session caller: must be authenticated AND hold a write-capable role.
    if pz_session:
        from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
        user = get_current_user_optional(pz_session=pz_session)
        if user is not None:
            # Fail-closed allowlist: only explicit write-capable roles pass.
            # Read-only, missing, empty, and unknown roles are all denied.
            if user.get("role") not in _WRITE_CAPABLE_ROLES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Role '{user.get('role')}' is not permitted to perform "
                        "this privileged action."
                    ),
                )
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )
