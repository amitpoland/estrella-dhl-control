"""admin_auth.py — one authenticated admin for tests whose routes moved onto RBAC.

Why this exists
---------------
``82327b52`` (*RBAC Phase C Area 1*) migrated 33 proposals/control/dashboard
routes off ``require_api_key`` and onto session guards — ``require_admin`` and
``require_role(...)``. Those two guards behave very differently from the one
they replaced:

    require_api_key   returns early when ``settings.api_key`` is unset and the
                      environment is not prod — "dev only, auth disabled".
    require_admin     Depends(get_current_user), unconditionally. No dev bypass,
    require_role(...) on any host, in any environment.

Tests never noticed the difference until the migration, because the test process
has no ``API_KEY``, so the old guard waved every request through. Some suites
overrode ``require_api_key`` explicitly; others relied on the bypass. After the
migration both groups get ``401 Not authenticated``, and the assertion under test
is never reached.

Why the override key is ``get_current_user``
--------------------------------------------
``require_admin`` and every ``require_role(...)`` closure both resolve through
``Depends(get_current_user)``. Overriding that one root satisfies every RBAC
guard at once — including ``require_role(...)``, which builds a **new function
object per call** and therefore cannot be used as a ``dependency_overrides`` key
at all from a test.

It also keeps the role check live. Overriding ``require_admin`` directly would
skip ``user["role"] != "admin"``; injecting a user instead means the real guard
still runs against the real role, so a route that rejects this user still
rejects it. Authentication is supplied; authorisation is still enforced.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Dict, Iterator

from app.auth.dependencies import get_current_user


class SharedAppLeakError(RuntimeError):
    """An unscoped admin override was aimed at an app that outlives the test."""


ADMIN_USER: Dict[str, Any] = {
    "id":          "test-admin",
    "email":       "admin@test.local",
    "role":        "admin",
    "is_active":   True,
    "is_approved": True,
}


def grant_admin(app):
    """Authenticate every RBAC guard on ``app`` as an admin.

    For an app the test builds and throws away. Returns ``app`` so it can be
    chained onto ``FastAPI()`` construction.

    Refuses the shared ``app.main:app`` singleton, which outlives the test — an
    override left on it would silently authenticate every suite that ran after,
    turning unrelated auth assertions green for the wrong reason. Use
    ``admin_session`` there. ``sys.modules.get`` rather than an import, so this
    check never constructs the real app just to compare against it.
    """
    main = sys.modules.get("app.main")
    if main is not None and app is getattr(main, "app", None):
        raise SharedAppLeakError(
            "grant_admin() was called on the shared app.main:app singleton. The "
            "override would outlive this test and authenticate every suite that "
            "runs after it. Use `with admin_session(app):` instead."
        )
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN_USER)
    return app


@contextmanager
def admin_session(app) -> Iterator[Any]:
    """``grant_admin`` scoped to a ``with`` block, restoring what was there before.

    Use this — never bare ``grant_admin`` — on the shared ``app.main:app``
    singleton. That object outlives the test, so an override left behind would
    silently authenticate unrelated suites that ran after it.
    """
    previous = app.dependency_overrides.get(get_current_user)
    # Set directly, not via grant_admin: the shared singleton is precisely what
    # this form exists to serve, and grant_admin refuses it by design.
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN_USER)
    try:
        yield app
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous
