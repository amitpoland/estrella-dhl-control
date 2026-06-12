"""
core/role_gate.py — Role-aware dependency factory for master-data writes.

Phase 0 scaffolding only. NOT wired into any route in this commit. Phase 2
will swap ``dependencies=[_auth]`` for the factory output on master write
endpoints.

Behavior contract
=================

The factory ``require_role_or_apikey(*roles)`` returns a FastAPI dependency
whose behavior is gated by ``settings.master_role_enforcement``:

  master_role_enforcement = False   (DEFAULT)
      Identical to ``require_api_key``. Either a valid X-API-Key OR a valid
      session cookie passes. Role of the cookie user is NOT checked.
      This guarantees Phase 2 introduction does not change live behavior
      until the flag is flipped.

  master_role_enforcement = True
      Two passes are allowed:
        (a) Direct X-API-Key matching ``settings.api_key`` — treated as
            ``master_admin`` for break-glass operations.
        (b) Session cookie present AND the user's role ∈ ``roles``. The
            three master-data roles are isolated from the existing
            ``viewer / auditor / logistics / accounts / admin`` ladder by
            design (operator instruction 2026-05-28).

Anything else returns 401 (no auth) or 403 (auth but wrong role).

Master roles (canonical, isolated)
==================================

    master_admin   — full CRUD + hard-delete + role assignment
    master_editor  — create/update/soft-delete on any master entity
    master_viewer  — read-only listing and detail

Master roles are NOT in the existing ``_ROLE_RANK`` ladder — they form a
separate namespace, so granting ``master_editor`` does not implicitly grant
``editor`` privileges anywhere else in the app, and the existing ``admin``
role does NOT automatically become ``master_admin``. A user can hold a
master role in addition to a normal role; the auth layer is extended in
Phase 2 to support that (out of scope for Phase 0).

Phase 0 wiring decision
=======================
Because role assignment in ``routes_auth.py`` still restricts to the legacy
set, this factory in Phase 0 only treats the master_* role strings as
*allowed names* when ``master_role_enforcement`` is True. Phase 2 will
extend the auth signup/role-update validators to accept these names.
"""
from __future__ import annotations

import hmac
from typing import Callable, Optional

from fastapi import Cookie, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ..auth.dependencies import get_current_user_optional
from .config import settings
from .security import require_api_key


# Canonical master role names — single source of truth.
MASTER_ADMIN  = "master_admin"
MASTER_EDITOR = "master_editor"
MASTER_VIEWER = "master_viewer"

MASTER_ROLES = frozenset({MASTER_ADMIN, MASTER_EDITOR, MASTER_VIEWER})


_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_role_or_apikey(*roles: str) -> Callable:
    """
    Dependency factory. Returns a FastAPI dependency that enforces
    role-based access when ``master_role_enforcement`` is on, and
    degrades to ``require_api_key`` semantics when it is off.

    Example
    -------
        @router.put("/{code}", dependencies=[
            Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))
        ])
        def upsert(...): ...

    Raises
    ------
    HTTPException(401) — no credentials presented (when enforcement on).
    HTTPException(403) — credentials present but role not in allowed set.
    """
    allowed = frozenset(roles) if roles else frozenset()

    # Defensive: reject programmer typos at dependency-construction time.
    unknown = allowed - MASTER_ROLES
    if unknown:
        raise ValueError(
            f"require_role_or_apikey called with unknown master roles: "
            f"{sorted(unknown)}; expected subset of {sorted(MASTER_ROLES)}"
        )

    def _dep(
        key:        Optional[str] = Security(_header),
        pz_session: Optional[str] = Cookie(default=None),
    ) -> None:
        # Flag OFF → degrade to require_api_key semantics. Identical to the
        # status quo so Phase 2 introduction is invisible until flag flip.
        if not settings.master_role_enforcement:
            return require_api_key(key=key, pz_session=pz_session)

        # Flag ON → role enforcement live.
        # (a) Direct X-API-Key — break-glass master_admin.
        if settings.api_key and key and hmac.compare_digest(key.encode("utf-8"), settings.api_key.encode("utf-8")):
            if MASTER_ADMIN in allowed or not allowed:
                return None
            # Even admin key must be permitted for this surface — when an
            # endpoint declares ``master_editor`` only, the admin key is
            # still allowed because admin ⊇ editor by convention.
            return None

        # (b) Session cookie — must be present, user must hold a permitted role.
        if not pz_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        user = get_current_user_optional(pz_session=pz_session)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        # Read role from user dict. Master roles are isolated, so the user
        # MUST hold a master_* role for master writes — holding ``admin``
        # alone is NOT sufficient (operator instruction 2026-05-28).
        user_role = (user.get("role") or "").strip()
        if user_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"Role '{user_role}' is not permitted for this master-data "
                        f"action. Required: {sorted(allowed)}"),
            )
        return None

    return _dep
