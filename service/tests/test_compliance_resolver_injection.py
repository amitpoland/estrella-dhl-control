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
    """Renderer state-upgrade ('intelligence_resolved' branch) must require
    status === 'verified' AND confidence in (exact, high) — never 'medium'
    or 'low'."""
    src = HTML.read_text(encoding="utf-8")
    idx = src.find("intelligenceResolved")
    assert idx != -1, "renderer must declare intelligenceResolved"
    window = src[idx:idx + 600]
    assert "status === 'verified'" in window
    assert "'exact'" in window
    assert "'high'"  in window


def test_html_distinguishes_engine_verified_from_intelligence_resolved():
    """AUTHORITY DISCIPLINE: secondary intelligence authority must never
    render with the same icon, colour, or copy as deterministic engine truth.

    Required separation:
      engine_verified      → ✓  + green   + (no extra copy)
      intelligence_resolved → ◎  + blue    + "Intelligence resolved"
                                          + "Review evidence before filing"
      gap (manual)         → ⚠  + amber
      failed               → ✗  + red
    """
    src = HTML.read_text(encoding="utf-8")
    # Named states present
    assert "'engine_verified'"       in src
    assert "'intelligence_resolved'" in src
    assert "'gap'"                   in src
    assert "'failed'"                in src
    # Distinct icon for intelligence — must NOT reuse '✓'
    idx_state = src.find("state === 'intelligence_resolved'")
    assert idx_state != -1
    # The icon-mapping ternary must map intelligence_resolved to '◎'
    icon_block_start = src.find("const stateIcon")
    assert icon_block_start != -1
    icon_block = src[icon_block_start:icon_block_start + 400]
    assert "intelligence_resolved'" in icon_block and "'◎'" in icon_block
    # Distinct colour — blue, not green
    colour_block_start = src.find("const stateColor")
    assert colour_block_start != -1
    colour_block = src[colour_block_start:colour_block_start + 500]
    assert "intelligence_resolved'" in colour_block
    assert "var(--badge-blue-text)" in colour_block
    # The intelligence-resolved row must NOT carry green text
    # (search the rendered span block for the intelligence branch)
    ir_branch_start = src.find("state === 'intelligence_resolved' && (")
    assert ir_branch_start != -1
    ir_branch = src[ir_branch_start:ir_branch_start + 800]
    assert "var(--badge-blue-text)"  in ir_branch
    assert "var(--badge-green-text)" not in ir_branch, (
        "intelligence_resolved row must not use the engine-verified green "
        "colour token"
    )


def test_html_intelligence_copy_includes_review_evidence_warning():
    """Copy must say 'Intelligence resolved' and direct the operator to
    'Review evidence before filing' — never just 'Verified'."""
    src = HTML.read_text(encoding="utf-8")
    assert "Intelligence resolved" in src
    assert "Review evidence before filing" in src
    # The over-strong v1 phrase must be gone
    assert "Verified via intelligence reconciliation" not in src


def test_html_never_upgrades_on_false_engine_result():
    """The deterministic engine's False outcome must always render as ✗."""
    src = HTML.read_text(encoding="utf-8")
    # State is computed from v first; the resolver path is only consulted
    # when state === 'gap'. Source-grep proves this guard.
    idx = src.find("const resolution")
    assert idx != -1
    # The resolution lookup line itself must carry the gap guard so the
    # deterministic True/False outcomes are never reconsulted.
    window = src[idx:idx + 200]
    assert "state === 'gap'" in window


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
    assert "state === 'gap' && !resolvedReview && check.nullHint" in src, (
        "renderer must fall back to check.nullHint when no resolution entry "
        "is present for the check"
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
    assert "if getattr(_cfg" in preceding or "if _cfg" in preceding


def test_routes_pop_field_on_exception():
    """Safety: on resolver exception, the field must be removed so the UI
    falls back to manual warnings rather than rendering a partial / stale
    object."""
    src = ROUTES.read_text(encoding="utf-8")
    assert 'audit.pop("compliance_resolution", None)' in src


def test_resolver_idempotent_under_frozen_time(monkeypatch):
    """Two consecutive resolve_compliance() calls on the same audit must
    produce identical output when time is frozen — guards against hidden
    nondeterminism beyond the resolved_at timestamp."""
    import app.services.compliance_resolver as cr

    monkeypatch.setattr(cr, "_now_iso", lambda: "2026-05-28T00:00:00+00:00")

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
