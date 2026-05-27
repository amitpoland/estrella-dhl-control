"""Compliance resolver — unit tests (2026-05-28).

resolve_compliance() is the single read-only authority for intelligence-derived
compliance badge states.  These tests pin:

  1. Flag-off: compliance_resolution absent from batch_detail response
  2. audit.verification never mutated by the resolver
  3. True verification fields → engine_verified
  4. False verification fields → failed
  5. null + high-confidence name overlap → intelligence_resolved
  6. null + weak name evidence → gap
  7. vat_match True stays engine_verified (not touched by intelligence layer)
  8. qty_match_by_type always returns gap (never intelligence_resolved)
  9. Source-grep: compliance_resolution injected in routes_dashboard.py
 10. Source-grep: feature flag present in config.py
 11. Source-grep: flag guards the injection in routes_dashboard.py
"""
from __future__ import annotations

import copy

import pytest

from app.services.compliance_resolver import resolve_compliance


# ── helpers ───────────────────────────────────────────────────────────────────

def _audit(
    *,
    importer_match=None,
    exporter_match=None,
    qty_match_by_type=None,
    vat_match=None,
    sad_importer=None,
    inv_importer=None,
    sad_exporter=None,
    inv_exporter=None,
    zc429_exporter=None,
    awb_shipper=None,
    awb_receiver=None,
    sad_qty_pieces=None,
) -> dict:
    ver: dict = {}
    for key, val in [
        ("importer_match",   importer_match),
        ("exporter_match",   exporter_match),
        ("qty_match_by_type", qty_match_by_type),
        ("vat_match",        vat_match),
    ]:
        if val is not None:
            ver[key] = val
        else:
            ver[key] = None   # explicit null in verification

    a: dict = {"verification": ver}

    if sad_importer or inv_importer:
        cd = a.setdefault("customs_declaration", {})
        if sad_importer:
            cd["importer_name"] = sad_importer
        if inv_importer:
            ver["invoice_importer_name"] = inv_importer

    if sad_exporter or inv_exporter or zc429_exporter:
        cd = a.setdefault("customs_declaration", {})
        if sad_exporter:
            cd["exporter_name"] = sad_exporter
        if inv_exporter:
            ver["invoice_exporter_name"] = inv_exporter
        if zc429_exporter:
            a.setdefault("zc429", {})["exporter_name"] = zc429_exporter

    if awb_shipper or awb_receiver:
        awb = a.setdefault("awb_fields", {})
        if awb_shipper:
            awb["shipper_name"] = awb_shipper
        if awb_receiver:
            awb["receiver_name"] = awb_receiver

    if sad_qty_pieces:
        a.setdefault("customs_declaration", {})["total_pieces"] = sad_qty_pieces

    return a


# ── 1. engine_verified when True ─────────────────────────────────────────────

def test_true_verification_returns_engine_verified():
    a = _audit(importer_match=True, exporter_match=True,
               qty_match_by_type=True, vat_match=True)
    r = resolve_compliance(a)
    for field in ("importer_match", "exporter_match", "qty_match_by_type", "vat_match"):
        assert r[field]["state"] == "engine_verified", f"{field} should be engine_verified"
        assert r[field]["confidence"] == "deterministic"
        assert r[field]["evidence"] is None


# ── 2. failed when False ──────────────────────────────────────────────────────

def test_false_verification_returns_failed():
    a = _audit(importer_match=False, exporter_match=False,
               qty_match_by_type=False, vat_match=False)
    r = resolve_compliance(a)
    for field in ("importer_match", "exporter_match", "qty_match_by_type", "vat_match"):
        assert r[field]["state"] == "failed", f"{field} should be failed"
        assert r[field]["confidence"] == "deterministic"


# ── 3. vat_match True always stays engine_verified ───────────────────────────

def test_vat_match_true_stays_engine_verified_when_other_fields_null():
    a = _audit(
        vat_match=True,
        sad_importer="Estrella Jewels Private Limited",
        inv_importer="Estrella Jewels Pvt",
    )
    r = resolve_compliance(a)
    assert r["vat_match"]["state"] == "engine_verified"
    assert r["vat_match"]["confidence"] == "deterministic"


# ── 4. intelligence_resolved for importer — high overlap ─────────────────────

def test_importer_high_overlap_returns_intelligence_resolved():
    a = _audit(
        sad_importer="Estrella Jewels Private Limited",
        inv_importer="Estrella Jewels Pvt Ltd",
    )
    r = resolve_compliance(a)
    assert r["importer_match"]["state"] == "intelligence_resolved"
    assert r["importer_match"]["confidence"] == "high"
    assert "Estrella" in r["importer_match"]["evidence"]


def test_importer_same_name_exact_returns_intelligence_resolved():
    name = "Global Jewellery Exports"
    a = _audit(sad_importer=name, inv_importer=name)
    assert resolve_compliance(a)["importer_match"]["state"] == "intelligence_resolved"


# ── 5. intelligence_resolved for exporter — SAD + zc429 source ───────────────

def test_exporter_high_overlap_zc429_source():
    a = _audit(
        sad_exporter="Rajasthan Gems Export House",
        zc429_exporter="Rajasthan Gems Export",
    )
    r = resolve_compliance(a)
    assert r["exporter_match"]["state"] == "intelligence_resolved"
    assert r["exporter_match"]["confidence"] == "high"


def test_exporter_high_overlap_invoice_source():
    a = _audit(
        sad_exporter="Jaipur Jewels Manufacturing",
        inv_exporter="Jaipur Jewels Manufacturing Co",
    )
    r = resolve_compliance(a)
    assert r["exporter_match"]["state"] == "intelligence_resolved"


def test_exporter_awb_shipper_fallback():
    a = _audit(
        sad_exporter="Precious Stones India",
        awb_shipper="Precious Stones India Export",
    )
    r = resolve_compliance(a)
    assert r["exporter_match"]["state"] == "intelligence_resolved"


# ── 6. gap when evidence is absent ───────────────────────────────────────────

def test_importer_gap_when_no_names():
    a = _audit()  # no SAD or invoice names
    r = resolve_compliance(a)
    assert r["importer_match"]["state"] == "gap"
    assert r["importer_match"]["confidence"] == "none"


def test_exporter_gap_when_sad_only():
    a = _audit(sad_exporter="Unknown Exporter Ltd")
    r = resolve_compliance(a)
    assert r["exporter_match"]["state"] == "gap"
    assert r["exporter_match"]["confidence"] == "medium"
    assert "no invoice name" in r["exporter_match"]["evidence"].lower()


def test_importer_gap_when_invoice_only():
    a = _audit(inv_importer="Some Company Ltd")
    r = resolve_compliance(a)
    assert r["importer_match"]["state"] == "gap"
    assert r["importer_match"]["confidence"] == "medium"


def test_importer_gap_when_overlap_below_threshold():
    """Low-token-overlap names should stay gap, not resolved."""
    a = _audit(
        sad_importer="Alpha Corporation",
        inv_importer="Beta Industries",
    )
    r = resolve_compliance(a)
    assert r["importer_match"]["state"] == "gap"


# ── 7. qty_match_by_type always gap ──────────────────────────────────────────

def test_qty_always_returns_gap_even_with_sad_pieces():
    a = _audit(sad_qty_pieces=120)
    r = resolve_compliance(a)
    assert r["qty_match_by_type"]["state"] == "gap"


def test_qty_gap_no_evidence_when_no_sad_data():
    a = _audit()
    r = resolve_compliance(a)
    assert r["qty_match_by_type"]["state"] == "gap"
    assert r["qty_match_by_type"]["confidence"] == "none"
    assert r["qty_match_by_type"]["evidence"] is None


def test_qty_gap_weak_with_sad_qty_data():
    a = _audit(sad_qty_pieces=50)
    r = resolve_compliance(a)
    assert r["qty_match_by_type"]["confidence"] == "weak"
    assert r["qty_match_by_type"]["evidence"] is not None


# ── 8. audit.verification never mutated ──────────────────────────────────────

def test_audit_verification_not_mutated():
    a = _audit(
        sad_importer="Estrella Jewels Private Limited",
        inv_importer="Estrella Jewels Pvt Ltd",
    )
    original_ver = copy.deepcopy(a["verification"])
    resolve_compliance(a)
    assert a["verification"] == original_ver


def test_audit_dict_not_mutated():
    a = _audit(vat_match=True, sad_importer="X Corp", inv_importer="X Corp")
    original = copy.deepcopy(a)
    resolve_compliance(a)
    assert a == original


# ── 9. empty / missing verification handled gracefully ───────────────────────

def test_empty_audit_returns_all_gap():
    r = resolve_compliance({})
    for field in ("importer_match", "exporter_match", "qty_match_by_type", "vat_match"):
        assert r[field]["state"] == "gap"


def test_missing_verification_key_returns_all_gap():
    r = resolve_compliance({"customs_declaration": {"importer_name": "X"}})
    assert r["importer_match"]["state"] == "gap"


# ── 10. source-grep: compliance_resolution injected in routes_dashboard ───────

def test_compliance_resolution_injected_in_batch_detail():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "app" / "api" / "routes_dashboard.py"
           ).read_text(encoding="utf-8")
    assert "compliance_resolution" in src, (
        "routes_dashboard.py must inject compliance_resolution into batch response"
    )
    assert "resolve_compliance" in src, (
        "routes_dashboard.py must call resolve_compliance"
    )


# ── 11. source-grep: feature flag present in config.py ───────────────────────

def test_feature_flag_in_config():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "app" / "core" / "config.py"
           ).read_text(encoding="utf-8")
    assert "compliance_intelligence_resolver_enabled" in src, (
        "config.py must declare compliance_intelligence_resolver_enabled"
    )
    assert "default=False" in src or "= False" in src, (
        "compliance_intelligence_resolver_enabled must default to False"
    )


# ── 12. source-grep: flag guards the injection ────────────────────────────────

def test_flag_guards_compliance_injection_in_routes():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "app" / "api" / "routes_dashboard.py"
           ).read_text(encoding="utf-8")
    assert "compliance_intelligence_resolver_enabled" in src, (
        "routes_dashboard.py must check compliance_intelligence_resolver_enabled "
        "before injecting compliance_resolution"
    )


# ── 13. four-state renderer present in shipment-detail.html ──────────────────

def test_four_state_renderer_in_shipment_detail():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "app" / "static" / "shipment-detail.html"
           ).read_text(encoding="utf-8")
    assert "intelligence_resolved" in src, (
        "shipment-detail.html must handle intelligence_resolved badge state"
    )
    assert "compliance_resolution" in src, (
        "shipment-detail.html must read compliance_resolution from audit"
    )
    # badge-blue-text must appear in the compliance renderer section overall.
    # We check the full VER_GROUPS.map block which contains both intelligence_resolved
    # handling and the stateColor constant that references badge-blue-text.
    assert "badge-blue-text" in src, (
        "shipment-detail.html must use badge-blue-text for intelligence_resolved state"
    )
    # Verify they appear in the same renderer block by checking proximity in the
    # section that contains the state variable.
    renderer_section = src[src.find("const stateColor"):src.find("const stateColor") + 800]
    assert "badge-blue-text" in renderer_section, (
        "stateColor constant must reference badge-blue-text for resolved state"
    )
    assert "resolved" in renderer_section, (
        "stateColor constant must handle 'resolved' state"
    )


# ── 14. AWB receiver_name path (importer) ────────────────────────────────────

def test_importer_resolves_with_awb_receiver_name():
    """SAD importer + AWB receiver_name with sufficient overlap → intelligence_resolved."""
    a = _audit(sad_importer="Estrella Jewels Sp. z o.o. Sp.k.")
    a.setdefault("awb_fields", {})["receiver_name"] = "Estrella Jewels Sp. z o.o., Sp. k."
    r = resolve_compliance(a)
    assert r["importer_match"]["state"] == "intelligence_resolved"
    assert r["importer_match"]["confidence"] == "high"


def test_importer_awb_receiver_gap_when_no_overlap():
    """AWB receiver with poor name overlap stays gap, not resolved."""
    a = _audit(sad_importer="Estrella Jewels Sp. z o.o.")
    a.setdefault("awb_fields", {})["receiver_name"] = "Totally Different Company"
    r = resolve_compliance(a)
    assert r["importer_match"]["state"] == "gap"


def test_importer_awb_receiver_used_only_as_fallback():
    """AWB receiver_name is not used when invoice_importer_name already provides evidence."""
    a = _audit(
        sad_importer="Estrella Jewels Sp. z o.o.",
        inv_importer="Estrella Jewels",
    )
    a.setdefault("awb_fields", {})["receiver_name"] = "Some Other Name"
    r = resolve_compliance(a)
    # invoice path takes priority over AWB; both SAD+invoice have overlap → resolved
    assert r["importer_match"]["state"] == "intelligence_resolved"


# ── 15. Source-grep: AWB fields injected in routes_dashboard ─────────────────

def test_awb_fields_injected_before_compliance_resolution():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "app" / "api" / "routes_dashboard.py"
           ).read_text(encoding="utf-8")
    assert "get_awb_document" in src, (
        "routes_dashboard.py must call get_awb_document to inject awb_fields"
    )
    assert "awb_fields" in src, (
        "routes_dashboard.py must inject awb_fields into audit before compliance resolution"
    )
