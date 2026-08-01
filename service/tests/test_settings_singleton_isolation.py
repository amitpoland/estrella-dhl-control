"""test_settings_singleton_isolation.py — the stale-Settings defect, pinned.

``importlib.reload(app.core.config)`` rebinds that module's ``settings`` name to
a newly constructed object.  app.main and the ~70 route modules captured the
ORIGINAL object at import time and keep it, so the process then holds two live
Settings objects.

A client fixture written as

    from app.core.config import settings          # captured at collection
    ...
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app) as c: ...

patches whichever object the *module-level import* happened to bind.  After a
reload that is no longer the object app.main's lifespan reads, so the patch
redirects nothing: startup initialises its ~20 databases under the previous
root, sharing reservation_queue.db with a still-running earlier lifespan's
background threads.  On Windows that lock contention hangs inside
``con.executescript(_DDL)`` until pytest-timeout's thread method hard-exits the
process, discarding every result after it — a suite-wide outage presenting as a
single test's timeout.

The fix is to patch the object app.main actually holds.  These tests pin both
halves: that patching the reloaded object does NOT redirect startup (the defect,
so a future rewrite back to the module-level-import form fails loudly), and that
patching ``app.main.settings`` DOES (the fix).  A third pair pins the
``_pin_settings_singleton`` conftest backstop that bounds a reload's blast
radius to the test that performed it.

Run: python -m pytest tests/test_settings_singleton_isolation.py -q
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

from fastapi.testclient import TestClient

# Deliberately NOT `from app.core.config import settings` — see module docstring.


# A database the lifespan creates unconditionally under settings.storage_root.
# reservation_queue.db is the one whose DDL blocked in the original incident;
# documents.db proves the redirect covers the ordinary operational DBs too.
_STARTUP_DBS = ("reservation_queue.db", "documents.db")


def _reload_config():
    """Reproduce the hazard: rebind app.core.config.settings to a fresh object.

    Returns (config_module, original_object).  The conftest
    _pin_settings_singleton fixture restores the binding after the test, so the
    divergence never escapes into a later test.
    """
    import app.core.config as cfg
    original = cfg.settings
    importlib.reload(cfg)
    assert cfg.settings is not original, (
        "reload no longer rebinds `settings` — if config.py changed to reuse a "
        "module-level singleton across reloads, this whole defect class is gone "
        "and these tests should be re-derived, not deleted"
    )
    return cfg, original


def _boot(storage_owner, tmp_path):
    """Enter/exit one app lifespan with storage_root patched on *storage_owner*."""
    import app.main as main_module
    with patch.object(storage_owner, "storage_root", tmp_path):
        with TestClient(main_module.app):
            pass


# ── The divergence itself ────────────────────────────────────────────────────

def test_reload_makes_config_settings_diverge_from_app_main():
    """After a reload, app.main and app.core.config hold DIFFERENT objects."""
    import app.main as main_module
    cfg, original = _reload_config()
    assert main_module.settings is original, (
        "app.main captured the original singleton and must not follow a reload"
    )
    assert cfg.settings is not main_module.settings


# ── The defect: patching the reloaded object redirects nothing ───────────────

def test_patching_reloaded_config_object_does_not_redirect_startup(tmp_path):
    """The failure mode, pinned.

    Patching ``app.core.config.settings`` after a reload leaves app.main's
    lifespan on the previous storage_root — so tmp_path stays empty.  If this
    test ever starts finding databases under tmp_path, the two objects have been
    unified and the client fixtures may go back to the simpler form.
    """
    cfg, _ = _reload_config()
    _boot(cfg.settings, tmp_path)
    created = [n for n in _STARTUP_DBS if (tmp_path / n).exists()]
    assert created == [], (
        f"expected the stale-object patch to redirect NOTHING, but startup "
        f"created {created} under tmp_path"
    )


# ── The fix: patching app.main.settings does redirect startup ────────────────

def test_patching_app_main_settings_redirects_startup_after_reload(tmp_path):
    """The hardened fixture shape survives a preceding config reload."""
    import app.main as main_module
    _reload_config()
    _boot(main_module.settings, tmp_path)
    missing = [n for n in _STARTUP_DBS if not (tmp_path / n).exists()]
    assert missing == [], (
        f"startup must initialise its databases under the patched root; "
        f"missing {missing} in {tmp_path}"
    )


def test_hardened_client_fixture_serves_requests_after_reload(tmp_path):
    """End-to-end: the fixture shape used by the registry tests still answers
    requests (and answers them from the redirected root) after a reload."""
    import app.main as main_module
    from app.services import document_db as ddb

    _reload_config()
    ddb.init_document_db(tmp_path / "documents.db")
    with patch.object(main_module.settings, "storage_root", tmp_path):
        with TestClient(main_module.app) as client:
            headers = {"X-API-KEY": main_module.settings.api_key or "test-key"}
            r = client.get(
                "/api/v1/upload/shipment/B-ISOLATION-PIN/documents", headers=headers
            )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0, "unknown batch must report an honest zero"


# ── The conftest backstop bounds the blast radius ────────────────────────────
#
# These two run in file order: the first diverges the binding, the second
# asserts the autouse _pin_settings_singleton fixture put it back.

def test_backstop_step_1_diverge_the_binding():
    cfg, original = _reload_config()
    assert cfg.settings is not original  # restored by the autouse fixture


def test_backstop_step_2_binding_was_restored():
    """A reload in an earlier test must not leave a later test patching a stale
    object — this is what makes the whole class order-independent."""
    import app.core.config as cfg
    import app.main as main_module
    assert cfg.settings is main_module.settings, (
        "_pin_settings_singleton (tests/conftest.py) must restore "
        "app.core.config.settings after any test that reloads the module"
    )


# ── Storage-root parity (the env half of the same guard) ─────────────────────

def test_reloaded_settings_still_points_at_the_session_sandbox():
    """conftest exports STORAGE_ROOT, so even the reload-created object resolves
    to the throwaway sandbox — never a real live storage root."""
    import app.main as main_module
    cfg, _ = _reload_config()
    assert cfg.settings.storage_root == main_module.settings.storage_root, (
        "a reload-created Settings must resolve storage_root to the same "
        "session sandbox; otherwise it writes into the real live root"
    )
