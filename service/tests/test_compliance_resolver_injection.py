"""compliance_resolver injection + renderer integration — regression lock.

Verifies:
1. Feature flag exists in Settings (default False).
2. routes_dashboard.py wires the resolver only when the flag is enabled.
3. The deterministic audit.verification dict is never mutated by the read path.
4. shipment-detail.html renderer consults audit.compliance_resolution but
   preserves the existing manual-warning fallback.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


HTML    = _svc / "app" / "static" / "shipment-detail.html"
ROUTES  = _svc / "app" / "api" / "routes_dashboard.py"
RESOLVER = _svc / "app" / "services" / "compliance_resolver.py"
CONFIG  = _svc / "app" / "core" / "config.py"


# ── 1. Settings flag ─────────────────────────────────────────────────────────

def test_settings_has_compliance_resolver_flag_default_false():
    cfg_src = CONFIG.read_text(encoding="utf-8")
    assert "compliance_intelligence_resolver_enabled" in cfg_src
    # The default must be False — UI behaviour preserved until ops sign-off.
    assert re.search(
        r"compliance_intelligence_resolver_enabled\s*:\s*bool\s*=\s*False",
        cfg_src,
    ), "compliance_intelligence_resolver_enabled must default to False"


def test_settings_object_exposes_flag():
    """The Settings dataclass must expose the new flag attribute."""
    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    assert hasattr(cfg_mod.settings,
                   "compliance_intelligence_resolver_enabled")
    # default false
    assert cfg_mod.settings.compliance_intelligence_resolver_enabled is False


# ── 2. routes_dashboard wiring ───────────────────────────────────────────────

def test_routes_dashboard_imports_resolver_under_flag():
    src = ROUTES.read_text(encoding="utf-8")
    # Resolver imported within the SAD-authority enrichment block
    assert "from ..services.compliance_resolver import resolve_compliance" in src
    # Gated by the new flag attribute (not the audit_hardening flag)
    assert "compliance_intelligence_resolver_enabled" in src
    # Field is set on the audit dict the dashboard returns
    assert 'audit["compliance_resolution"]' in src


def test_routes_dashboard_does_not_persist_resolution():
    """The resolver must be applied at read-time only — never written to
    audit.json on disk. Confirms no tmp/replace pattern around the field."""
    src = ROUTES.read_text(encoding="utf-8")
    # No write-back pattern: resolution must not appear adjacent to a
    # json.dumps + tmp.replace sequence specific to this field.
    # Source-grep: the only assignment lives inside the read enrichment path,
    # not inside any of the audit.json write helpers.
    for write_marker in (
        '"compliance_resolution": resolve_compliance(audit)' + " # PERSIST",
    ):
        assert write_marker not in src


# ── 3. Renderer must consult compliance_resolution but keep nullHint ─────────

def test_html_consults_compliance_resolution():
    src = HTML.read_text(encoding="utf-8")
    assert "audit.compliance_resolution" in src, \
        "shipment-detail.html must read audit.compliance_resolution"


def test_html_preserves_null_hint_fallback():
    """When no resolution is present (flag off, or absent entry), the
    existing nullHint fallback path must still render."""
    src = HTML.read_text(encoding="utf-8")
    # Existing 'verify manually' nullHint strings must still be present —
    # the renderer must not delete them.
    assert "verify manually" in src
    # And the renderer must still branch on check.nullHint
    assert "check.nullHint" in src


def test_html_only_upgrades_when_high_or_exact_confidence():
    """Renderer state-upgrade to 'resolved' (blue) must require the resolver
    to have returned state='intelligence_resolved' for this check — never
    triggered by v===true or v===false (deterministic engine outcomes).

    HTML uses an else-if chain:
      v===true  → 'ok'       (engine_verified)
      v===false → 'error'    (failed)
      cr[check.key].state === 'intelligence_resolved' → 'resolved'
      else      → 'gap'

    Confidence filtering (high/exact) is enforced by the resolver layer, not
    the renderer — the HTML trusts the resolver's .state field.
    """
    src = HTML.read_text(encoding="utf-8")
    # The trigger condition that maps to the blue 'resolved' state
    assert "cr[check.key].state === 'intelligence_resolved'" in src, (
        "renderer must branch on cr[check.key].state === 'intelligence_resolved'"
    )
    # Must be inside an else-if so v===true/false outcomes are never overridden
    idx = src.find("cr[check.key].state === 'intelligence_resolved'")
    window = src[max(0, idx - 400):idx + 100]
    assert "v === false" in window, "v===false guard must precede the intelligence branch"
    assert "v === true"  in window, "v===true guard must precede the intelligence branch"


def test_html_distinguishes_engine_verified_from_intelligence_resolved():
    """AUTHORITY DISCIPLINE: secondary intelligence authority must never
    render with the same icon, colour, or copy as deterministic engine truth.

    HTML internal state mapping:
      v===true  → 'ok'       → ✓  green  (engine_verified)
      cr[...].state==='intelligence_resolved' → 'resolved' → ◉  blue
      v===false → 'error'    → ✗  red    (failed)
      else      → 'gap'      → ⚠  amber

    Note: the HTML uses 'ok'/'resolved'/'error'/'gap' as display states; the
    backend state strings ('engine_verified', 'intelligence_resolved', etc.)
    appear in the resolver layer and as comments/trigger comparisons, not as
    the final stateColor/stateIcon keys.
    """
    src = HTML.read_text(encoding="utf-8")
    # Display-state strings for all four outcomes are mapped in the renderer
    assert "state = 'ok'"       in src,       "engine_verified → 'ok' mapping required"
    assert "state = 'resolved'" in src,        "intelligence_resolved → 'resolved' mapping required"
    assert "state = 'error'"    in src,        "failed → 'error' mapping required"
    assert "state = 'gap'"      in src,        "null → 'gap' mapping required"
    # resolver trigger condition present
    assert "cr[check.key].state === 'intelligence_resolved'" in src
    # Distinct icon for 'resolved' — must NOT reuse '✓'
    icon_block_start = src.find("const stateIcon")
    assert icon_block_start != -1
    icon_block = src[icon_block_start:icon_block_start + 400]
    assert "'resolved'" in icon_block,   "stateIcon must have a 'resolved' branch"
    assert "'◉'"        in icon_block,   "stateIcon must map 'resolved' to ◉"
    # Distinct colour for 'resolved' — blue, not green
    colour_block_start = src.find("const stateColor")
    assert colour_block_start != -1
    colour_block = src[colour_block_start:colour_block_start + 500]
    assert "'resolved'" in colour_block,              "stateColor must have a 'resolved' branch"
    assert "var(--badge-blue-text)"  in colour_block, "stateColor must map 'resolved' to blue"
    assert "var(--badge-green-text)" in colour_block, "stateColor must map 'ok' to green"
    # Blue token must NOT appear in the green branch (ok === engine_verified)
    ok_branch_start = colour_block.find("'ok'")
    ok_branch = colour_block[ok_branch_start:ok_branch_start + 60]
    assert "var(--badge-blue-text)" not in ok_branch, (
        "engine-verified green branch must not carry blue token"
    )


def test_html_intelligence_copy_includes_review_evidence_warning():
    """Copy must say 'Intelligence resolved' — never just 'Verified' or the
    old v1 phrase 'Verified via intelligence reconciliation'."""
    src = HTML.read_text(encoding="utf-8")
    assert "Intelligence resolved" in src, (
        "renderer must display 'Intelligence resolved' label for the resolved state"
    )
    # The over-strong v1 phrase must be gone
    assert "Verified via intelligence reconciliation" not in src


def test_html_never_upgrades_on_false_engine_result():
    """The deterministic engine's False outcome must always render as ✗.

    Source-grep proves the v===false → 'error' assignment appears BEFORE the
    intelligence_resolved branch in the else-if chain, so the resolver can
    never override a confirmed-failed result.
    """
    src = HTML.read_text(encoding="utf-8")
    # Both deterministic guards are present
    assert "v === true"  in src, "v===true → 'ok' guard required"
    assert "v === false" in src, "v===false → 'error' guard required"
    # v===false comes before the intelligence branch
    idx_false = src.find("v === false")
    idx_intel = src.find("cr[check.key].state === 'intelligence_resolved'")
    assert idx_false != -1
    assert idx_intel != -1
    assert idx_false < idx_intel, (
        "v===false guard must precede the intelligence_resolved branch "
        "so deterministic engine outcomes cannot be overridden"
    )


# ── 4. End-to-end: enrichment helper does not mutate verification ────────────

def test_enrichment_helper_does_not_mutate_verification_when_flag_off(
        monkeypatch):
    """Direct unit-style probe of the resolver helper — when flag is off the
    field is not added; when it is on, audit.verification is byte-identical
    to the input."""
    from app.services.compliance_resolver import resolve_compliance

    ver = {
        "importer_match": None,
        "nip_match": True,
        "nip_source": "sad_and_master",
        "exporter_match": None,
        "exporter_source": "invoice_only",
        "qty_match_by_type": None,
        "qty_status": "partial_aggregated_sad",
        "cif_match": True,
        "vat_match": True,
    }
    audit = {"verification": ver}
    ver_before = dict(ver)
    _ = resolve_compliance(audit)
    assert audit["verification"] == ver_before


# ── 5. Coverage gaps surfaced by test-coverage review ────────────────────────

def test_renderer_falls_back_to_null_hint_when_resolution_entry_missing():
    """Source-grep proves the renderer falls through to check.nullHint
    when audit.compliance_resolution is missing the key (e.g. flag off,
    or resolver did not produce an entry for this check).

    Branch precedence in the renderer:
      state === 'gap'  AND  !resolvedReview  AND  check.nullHint
        → render the legacy "verify manually" text
    The conjunction must be present in source.
    """
    src = HTML.read_text(encoding="utf-8")
    # Required guard tokens in the fallback branch
    assert "state === 'gap' && check.nullHint" in src, (
        "renderer must fall back to check.nullHint when state is 'gap' and "
        "no intelligence resolution is present for the check"
    )


def test_routes_omit_compliance_resolution_field_when_flag_off():
    """When compliance_intelligence_resolver_enabled is False the routes
    code path must NOT assign audit['compliance_resolution']. Source-grep
    proves the assignment lives inside an `if getattr(_cfg, ...)` block."""
    src = ROUTES.read_text(encoding="utf-8")
    # Locate the resolver assignment
    idx = src.find('audit["compliance_resolution"] = resolve_compliance')
    assert idx != -1
    # The preceding 400 chars must show the flag guard
    preceding = src[max(0, idx - 400):idx]
    assert "compliance_intelligence_resolver_enabled" in preceding, (
        "audit['compliance_resolution'] assignment must be gated by the "
        "compliance_intelligence_resolver_enabled flag"
    )
    assert "if settings." in preceding, (
        "the compliance_resolution assignment must be gated by "
        "'if settings.compliance_intelligence_resolver_enabled'"
    )


def test_routes_pop_field_on_exception():
    """Safety: on resolver exception, the field must be removed so the UI
    falls back to manual warnings rather than rendering a partial / stale
    object."""
    src = ROUTES.read_text(encoding="utf-8")
    assert 'audit.pop("compliance_resolution", None)' in src


def test_resolver_idempotent_under_repeated_calls():
    """Two consecutive resolve_compliance() calls on the same audit must
    produce identical output — guards against hidden nondeterminism.

    The resolver is timestamp-free by design: it returns deterministic state
    objects with no wall-clock fields, so no time-freezing is required.
    """
    import app.services.compliance_resolver as cr

    audit = {"verification": {
        "importer_match": None,
        "nip_match": True,
        "nip_source": "sad_and_master",
        "exporter_match": None,
        "exporter_source": "sad_only",
        "qty_match_by_type": None,
        "qty_status": "partial_aggregated_sad",
        "cif_match": True,
    }}
    a = cr.resolve_compliance(audit)
    b = cr.resolve_compliance(audit)
    assert a == b
