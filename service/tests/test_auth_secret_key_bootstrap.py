"""test_auth_secret_key_bootstrap.py — the test process must hold a usable
session signing key, by whichever of conftest's two mechanisms applies.

Why this file exists
--------------------
`Settings.auth_secret_key` defaults to "" and is passed straight to
jwt.encode / jwt.decode, so an empty key means every token-minting test fails on
`InvalidKeyError` before reaching its assertion.  conftest.py fixes that twice
over: an env export before `app.core.config` is imported, and an unconditional
repair after it.

An earlier revision had only the export, placed AFTER the import, and was a
silent no-op — identical failure sets, 6 HMAC errors before and after.  Nothing
detected it.  These pins are the detection.

They are deliberately BEHAVIOURAL, not source greps.  A test asserting "line A
appears before line B in conftest.py" would stay green if the key were renamed,
if the exported value were empty, or if pydantic stopped reading the environment
— and would go red on a harmless refactor.  This repo already carries a cohort of
source-grep pins in its documented red baseline; adding another is adding debt.

The storage half of the same conftest bootstrap is pinned the same way, in
test_settings_singleton_isolation.py::test_reloaded_settings_still_points_at_the_session_sandbox.
This is its missing auth twin.

Run: python -m pytest tests/test_auth_secret_key_bootstrap.py -q
"""
from __future__ import annotations

import importlib
import os

import pytest


def test_settings_singleton_has_a_usable_signing_key():
    """The live singleton must carry a non-empty key.

    Fails if the export is misplaced AND the repair is removed — i.e. the exact
    regression that shipped silently once.
    """
    from app.core.config import settings

    assert settings.auth_secret_key, (
        "app.core.config.settings.auth_secret_key is empty — every token-minting "
        "test will fail on InvalidKeyError. conftest.py is meant to guarantee "
        "this; check both the env export and the unconditional repair."
    )


def test_app_main_sees_the_same_usable_key():
    """app.main captured the singleton at import; it must see the key too.

    Patching a settings object app.main does not hold redirects nothing — the
    defect class this suite already pins for storage_root.
    """
    import app.main as main_module

    assert main_module.settings.auth_secret_key


def test_reload_created_settings_also_resolves_a_key():
    """The auth twin of test_reloaded_settings_still_points_at_the_session_sandbox.

    `importlib.reload(app.core.config)` constructs a NEW Settings that re-reads
    the environment. It must also resolve a key — this is the half the
    post-import repair cannot reach, and the half that breaks if someone deletes
    the env export as 'redundant' because the repair already fixes the singleton.
    """
    import app.core.config as cfg

    original = cfg.settings
    try:
        reloaded = importlib.reload(cfg)
        assert reloaded.settings is not original, "reload did not rebind settings"
        assert reloaded.settings.auth_secret_key, (
            "a reload-created Settings resolved an EMPTY auth_secret_key — the "
            "AUTH_SECRET_KEY env export is missing or empty. The post-import "
            "repair in conftest cannot help here: it only touches the object "
            "that existed at conftest import time."
        )
    finally:
        # _pin_settings_singleton (conftest) restores the binding after the test,
        # but restore here too so nothing downstream in THIS module sees the
        # diverged object.
        cfg.settings = original


def test_token_round_trip_actually_works():
    """Sign and verify for real — the end the key exists for.

    Reproduces the original failure signature exactly: with an empty key this
    raises InvalidKeyError inside create_token, which is what the 6 log
    occurrences were.
    """
    from app.auth.service import create_token, decode_token

    token = create_token("pin-user", "admin")
    claims = decode_token(token)
    assert claims is not None, "a freshly minted token failed to verify"
    assert claims.get("sub") == "pin-user"


def test_empty_env_export_is_repaired_not_echoed():
    """A host exporting AUTH_SECRET_KEY="" must NOT reinstate the defect.

    `os.environ.setdefault` is presence-based, not truthiness-based: an unset CI
    secret referenced in an `env:` block resolves to "", which setdefault
    declines to overwrite. An earlier revision then assigned
    `os.environ["AUTH_SECRET_KEY"]` back onto the singleton — echoing the same
    empty string it was meant to rescue, and silently restoring the pre-fix
    failure set on that host only.

    Asserts the invariant conftest must maintain: whatever the host did, the
    process ends up with a non-empty key in BOTH places.
    """
    assert os.environ.get("AUTH_SECRET_KEY"), (
        "AUTH_SECRET_KEY is empty in the environment — a reload-created Settings "
        "would resolve an empty key"
    )

    from app.core.config import settings

    assert settings.auth_secret_key


@pytest.mark.parametrize("attr", ["auth_secret_key"])
def test_key_is_not_a_production_shaped_secret(attr):
    """Guard against a real secret leaking in via the host environment.

    conftest uses setdefault, so a host exporting a genuine AUTH_SECRET_KEY wins
    and the suite signs with it. That is intentional (never clobber a host
    value), but a production key is generated as 32 random bytes hex — 64 hex
    chars. If one is present, fail loudly rather than sign test tokens with it
    and risk it reaching a CI log via a failure dump.
    """
    from app.core.config import settings

    value = getattr(settings, attr)
    looks_production = len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)
    assert not looks_production, (
        f"settings.{attr} looks like a real 32-byte-hex production secret. The "
        f"test suite should not sign tokens with it — unset AUTH_SECRET_KEY in "
        f"this environment so conftest supplies the test-only value."
    )
