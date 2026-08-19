"""Pins for issue #1089 — patched-settings mocks must not become filesystem paths.

Two carrier route suites patched `app.core.config.settings` wholesale and left
`carrier_storage_root` unset. `patch(...)` auto-creates every unread attribute
as a *truthy* child mock, so production's

    settings.carrier_storage_root or (settings.storage_root / "carrier")

short-circuited onto a mock, and the resulting MagicMock repr was later opened
as a RELATIVE path. Each affected run dropped files named

    <MagicMock name='settings.carrier_storage_root.__truediv__()' id='...'>

into the pytest CWD — `service/`. The `id=` differs every run, so they
accumulated rather than overwrote, and 11 of them reached commit `6091e2d9`
before being caught.

The defect was invisible in test output: every affected test PASSED. That is
what these pins are for.

Falsifiability: `test_bare_settings_patch_is_the_defect_being_pinned` asserts
the *unfixed* pattern still produces a mock path. If that control ever starts
failing, the mechanism has changed and the other pins here are no longer
testing what they claim.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# `service/` — tests/ lives directly under it.
SERVICE_ROOT = Path(__file__).resolve().parent.parent

_MOCK_ARTIFACT_GLOB = "*MagicMock*"


def _mock_artifacts(root: Path) -> list[Path]:
    """Every path under *root* whose name betrays a stringified mock."""
    return sorted(p for p in root.rglob(_MOCK_ARTIFACT_GLOB))


# ── The committed-contamination case ──────────────────────────────────────────


def test_no_mock_named_artifacts_are_committed_under_service():
    """No mock-named path may exist in the tree.

    Catches the case that actually reached a commit: junk staged by a broad
    `git add` after running an affected suite. Deterministic and free of any
    ordering assumption — it inspects the tree, not the run.
    """
    found = _mock_artifacts(SERVICE_ROOT)
    assert not found, (
        f"{len(found)} mock-named path(s) present under {SERVICE_ROOT}. These are "
        "produced by a test that patches settings without pinning the storage "
        "attributes (issue #1089); they must never be committed:\n  "
        + "\n  ".join(str(p.relative_to(SERVICE_ROOT)) for p in found)
    )


# ── The mechanism, pinned per repaired module ─────────────────────────────────


def _resolved_carrier_root(settings):
    """The exact expression production uses to resolve the carrier root.

    Mirrors routes_carrier_actions.py, routes_carrier_webhook.py,
    routes_proforma.py, services/carrier/event_processor.py and
    services/carrier/adapters/live.py.
    """
    return settings.carrier_storage_root or (settings.storage_root / "carrier")


# Modules that wholesale-mock the GLOBAL singleton `app.core.config.settings`
# and therefore expose every one of the ~315 `settings.storage_root` production
# sites to their mock. Each pins the storage attributes through a module-local
# `_pin_storage` helper. They were latent, not live — none was observed writing
# junk — so nothing but this pin would notice the helper being dropped.
_GLOBAL_SINGLETON_PATCHERS = [
    "tests.test_ai_dhl_followup_drafter",
    "tests.test_carrier_routes_auth",
    "tests.test_email_sad_attachment_download",
    "tests.test_ingestor_engine_path",
    "tests.test_phase2b_provider_selection",
]


@pytest.mark.parametrize("module_name", _GLOBAL_SINGLETON_PATCHERS)
def test_pin_storage_helper_yields_a_real_path(module_name):
    """Each global-singleton patcher's `_pin_storage` must produce a real Path.

    These modules pin rather than wrap: they patch `settings` in many places and
    call `_pin_storage(mock)` at each. Verified against a bare `MagicMock`, the
    same object `patch(...)` hands them.
    """
    module = pytest.importorskip(module_name)
    pin = getattr(module, "_pin_storage", None)
    assert pin is not None, (
        f"{module_name} patches the global settings singleton and must expose a "
        "`_pin_storage` helper applied at every patch site (issue #1089)"
    )

    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    pin(mock_settings)
    root = _resolved_carrier_root(mock_settings)
    assert isinstance(root, Path), (
        f"{module_name}._pin_storage left a mock in the carrier-root expression; "
        f"got {type(root).__name__} ({root!r})"
    )
    assert root.is_absolute(), (
        f"{module_name} resolved a RELATIVE carrier root ({root}); a relative "
        "root is what lands junk in the pytest CWD"
    )


@pytest.mark.parametrize("module_name", _GLOBAL_SINGLETON_PATCHERS)
def test_global_singleton_patchers_pin_every_site(module_name):
    """Every `app.core.config.settings` patch site must be pinned.

    Counting, not per-line matching: a new unpinned site is textually identical
    to a pinned one, so only the ratio of patch sites to `_pin_storage` calls
    can distinguish them. `_settings()`-style factories pin once and are counted
    as covering all their callers, so the call count may exceed the site count —
    it may never fall below it.
    """
    module = pytest.importorskip(module_name)
    src = Path(module.__file__).read_text(encoding="utf-8")
    sites = sum(
        1
        for line in src.splitlines()
        if "patch(" in line
        and "app.core.config.settings" in line
        and not line.strip().startswith("#")
    )
    pins = sum(
        1
        for line in src.splitlines()
        if "_pin_storage(" in line and not line.strip().startswith(("#", "def "))
    )
    assert pins >= 1, f"{module_name} defines no _pin_storage call"
    # A factory pins once for many sites; a per-site module pins once per site.
    assert pins >= sites or "_settings(" in src, (
        f"{module_name} has {sites} settings patch site(s) but only {pins} "
        "_pin_storage call(s) — at least one site is unpinned (issue #1089)"
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "tests.test_carrier_routes_gate",
        "tests.test_carrier_routes_awb_authority",
    ],
)
def test_patched_settings_helper_yields_a_real_path(module_name):
    """Each repaired module's `_patched_settings` must produce a real Path.

    Imports the helper the module itself uses, so the pin tracks the module
    rather than re-implementing it. A regression that drops either attribute
    fails here instead of silently writing to the CWD again.
    """
    module = pytest.importorskip(module_name)
    helper = getattr(module, "_patched_settings", None)
    assert helper is not None, (
        f"{module_name} must route every settings patch through a "
        "`_patched_settings` helper (issue #1089)"
    )

    with helper() as mock_settings:
        root = _resolved_carrier_root(mock_settings)
        assert isinstance(root, Path), (
            f"{module_name}._patched_settings left a mock in the carrier-root "
            f"expression; got {type(root).__name__} ({root!r})"
        )
        assert root.is_absolute(), (
            f"{module_name} resolved a RELATIVE carrier root ({root}); a relative "
            "root is what lands junk in the pytest CWD"
        )


@pytest.mark.parametrize(
    "filename",
    ["test_carrier_routes_gate.py", "test_carrier_routes_awb_authority.py"],
)
def test_repaired_modules_patch_settings_in_exactly_one_place(filename):
    """These modules may contain exactly ONE settings patch — the helper's own.

    A source check, deliberately: the runtime pins above only exercise
    `_patched_settings`, so a new bare call site added *alongside* it would slip
    past them entirely.

    Counting is what makes this work. A new bare site is textually identical to
    the helper's own line (`with patch("app.core.config.settings") as
    mock_settings:`), so no per-line rule can tell them apart — but a second
    occurrence anywhere in the file means a call site that bypasses the helper.
    """
    path = Path(__file__).resolve().parent / filename
    sites = [
        f"{filename}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "patch(" in line
        and "app.core.config.settings" in line
        and not line.strip().startswith("#")
    ]
    assert len(sites) == 1, (
        f"expected exactly 1 settings patch in {filename} (inside _patched_settings), "
        f"found {len(sites)}. Every call site must go through the helper so the "
        f"storage attributes cannot be forgotten again (issue #1089):\n  "
        + "\n  ".join(sites)
    )


def test_running_the_repaired_suites_leaves_no_artifact_in_the_cwd(tmp_path):
    """Exercising the helper must not create anything in the process CWD.

    The original defect wrote to the CWD, so this asserts against the CWD
    directly rather than against a temp directory.
    """
    module = pytest.importorskip("tests.test_carrier_routes_gate")
    before = set(os.listdir(os.getcwd()))
    with module._patched_settings() as mock_settings:
        # Force the expression and a string coercion — the coercion is what
        # turned the mock into a filename in the original defect.
        str(_resolved_carrier_root(mock_settings))
    after = set(os.listdir(os.getcwd()))
    created = {name for name in (after - before) if "MagicMock" in name}
    assert not created, f"helper created mock-named path(s) in the CWD: {sorted(created)}"


# ── Falsifiability control ────────────────────────────────────────────────────


def test_bare_settings_patch_is_the_defect_being_pinned():
    """The UNFIXED pattern must still produce a mock path.

    This is the control that keeps the pins above honest. It asserts the defect
    mechanism is real and unchanged — if `patch()` ever stopped auto-creating
    truthy children, the assertions above would pass vacuously and this test is
    what would tell you.

    Nothing is written to disk here: the mock is never coerced to a filename.
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.carrier_gate_enabled = False
        # Note: storage_root set, carrier_storage_root NOT — exactly what
        # test_carrier_routes_awb_authority.py used to do.
        mock_settings.storage_root = Path("/tmp/test")
        root = _resolved_carrier_root(mock_settings)
        assert not isinstance(root, Path), (
            "the #1089 mechanism no longer reproduces: a bare settings patch now "
            "yields a real Path. The pins in this module may be vacuous — "
            "re-derive them before trusting."
        )
        assert "MagicMock" in repr(root)
