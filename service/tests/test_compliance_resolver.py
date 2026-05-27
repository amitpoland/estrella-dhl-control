"""compliance_resolver — unit tests.

Pins the v1 resolver behaviour for importer_match, exporter_match,
qty_match_by_type. The resolver is a pure, read-time secondary authority
that never mutates audit.verification and never persists.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.compliance_resolver import (  # noqa: E402
    RESOLVER_VERSION,
    TARGET_CHECKS,
    resolve_compliance,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _audit(ver: dict) -> dict:
    return {"verification": ver}


# ── importer_match ───────────────────────────────────────────────────────────

def test_importer_master_nip_fallback_verified_high():
    a = _audit({
        "importer_match": None,
        "nip_match": True,
        "nip_source": "sad_and_master",
        "sad_importer_name": "ESTRELLA JEWELS SP. Z O.O.",
        "invoice_importer_name": "",
        "invoice_vat": "",
    })
    r = resolve_compliance(a)["importer_match"]
    assert r["resolver"]   == "intelligence"
    assert r["status"]     == "verified"
    assert r["confidence"] == "high"
    assert r["resolved_by"] == RESOLVER_VERSION
    assert any(e["source"] == "verification.nip_source" for e in r["evidence"])


def test_importer_nip_match_both_sides_verified_high():
    a = _audit({
        "importer_match": None,
        "nip_match": True,
        "nip_source": "invoice_and_sad",
        "invoice_vat": "PL5213870274",
    })
    r = resolve_compliance(a)["importer_match"]
    assert r["status"] == "verified"
    assert r["confidence"] == "high"


def test_importer_no_nip_evidence_stays_manual_low():
    a = _audit({
        "importer_match": None,
        "nip_match": None,
        "nip_source": "neither",
        "sad_importer_name": "",
        "invoice_importer_name": "",
    })
    r = resolve_compliance(a)["importer_match"]
    assert r["resolver"]   == "manual_required"
    assert r["status"]     == "review"
    assert r["confidence"] == "low"


def test_importer_true_is_skipped():
    a = _audit({"importer_match": True})
    assert "importer_match" not in resolve_compliance(a)


def test_importer_false_is_skipped():
    a = _audit({"importer_match": False})
    assert "importer_match" not in resolve_compliance(a)


# ── exporter_match ───────────────────────────────────────────────────────────

def test_exporter_invoice_only_verified_high():
    a = _audit({
        "exporter_match": None,
        "exporter_source": "invoice_only",
    })
    r = resolve_compliance(a)["exporter_match"]
    assert r["status"]     == "verified"
    assert r["confidence"] == "high"
    assert "SAD" in r["reason"]


def test_exporter_sad_only_keeps_manual_medium():
    a = _audit({
        "exporter_match": None,
        "exporter_source": "sad_only",
        "sad_exporter_name": "SOME SUPPLIER",
    })
    r = resolve_compliance(a)["exporter_match"]
    assert r["resolver"]   == "manual_required"
    assert r["status"]     == "review"
    assert r["confidence"] == "medium"


def test_exporter_neither_low_confidence_manual():
    a = _audit({
        "exporter_match": None,
        "exporter_source": "neither",
    })
    r = resolve_compliance(a)["exporter_match"]
    assert r["resolver"]   == "manual_required"
    assert r["confidence"] == "low"


# ── qty_match_by_type ────────────────────────────────────────────────────────

def test_qty_partial_aggregated_with_cif_match_verified_high():
    a = _audit({
        "qty_match_by_type": None,
        "qty_status": "partial_aggregated_sad",
        "cif_match": True,
    })
    r = resolve_compliance(a)["qty_match_by_type"]
    assert r["status"]     == "verified"
    assert r["confidence"] == "high"


def test_qty_partial_aggregated_without_cif_stays_manual_medium():
    a = _audit({
        "qty_match_by_type": None,
        "qty_status": "partial_aggregated_sad",
        "cif_match": None,
    })
    r = resolve_compliance(a)["qty_match_by_type"]
    assert r["resolver"]   == "manual_required"
    assert r["confidence"] == "medium"


def test_qty_not_verified_stays_manual_low():
    a = _audit({
        "qty_match_by_type": None,
        "qty_status": "not_verified",
    })
    r = resolve_compliance(a)["qty_match_by_type"]
    assert r["resolver"]   == "manual_required"
    assert r["confidence"] == "low"


# ── purity / safety invariants ───────────────────────────────────────────────

def test_resolver_does_not_mutate_audit_verification():
    a = _audit({
        "importer_match": None,
        "nip_match": True,
        "nip_source": "sad_and_master",
        "exporter_match": None,
        "exporter_source": "invoice_only",
        "qty_match_by_type": None,
        "qty_status": "partial_aggregated_sad",
        "cif_match": True,
        "vat_match": True,
    })
    before = copy.deepcopy(a)
    _ = resolve_compliance(a)
    assert a == before, "resolver mutated input audit dict"


def test_resolver_skips_target_checks_absent_from_verification():
    """If verification dict has no entry for a target check, resolver omits it."""
    a = _audit({"vat_match": True})
    out = resolve_compliance(a)
    for k in TARGET_CHECKS:
        assert k not in out


def test_resolver_handles_empty_audit_safely():
    assert resolve_compliance({}) == {}
    assert resolve_compliance({"verification": {}}) == {}


def test_resolver_never_overrides_vat_or_other_checks():
    """Resolver only touches the three target checks — VAT/CIF/refs untouched."""
    a = _audit({
        "vat_match": False,
        "cif_match": False,
        "invoice_refs_match": True,
        "importer_match": None,
        "nip_match": True,
        "nip_source": "invoice_and_sad",
    })
    out = resolve_compliance(a)
    assert set(out.keys()) <= set(TARGET_CHECKS)
    assert "vat_match"          not in out
    assert "cif_match"          not in out
    assert "invoice_refs_match" not in out


def test_resolver_provenance_fields_present_on_every_entry():
    a = _audit({
        "importer_match": None,
        "nip_match": True,
        "nip_source": "sad_and_master",
        "exporter_match": None,
        "exporter_source": "sad_only",
        "qty_match_by_type": None,
        "qty_status": "partial_aggregated_sad",
        "cif_match": True,
    })
    out = resolve_compliance(a)
    for key, entry in out.items():
        assert entry["resolved_by"] == RESOLVER_VERSION
        assert entry["resolved_at"]
        assert entry["resolver"] in ("intelligence", "manual_required")
        assert entry["status"]   in ("verified", "review")
        assert entry["confidence"] in ("exact", "high", "medium", "low")
        assert isinstance(entry["evidence"], list)
        assert isinstance(entry["reason"], str) and entry["reason"]


def test_high_or_exact_required_for_verified_status():
    """Spec: medium/low confidence MUST stay manual_required/review."""
    a = _audit({
        "exporter_match":   None,
        "exporter_source":  "sad_only",      # produces medium
        "qty_match_by_type": None,
        "qty_status":        "partial_aggregated_sad",
        "cif_match":         None,           # produces medium
    })
    out = resolve_compliance(a)
    for entry in out.values():
        if entry["confidence"] in ("medium", "low"):
            assert entry["status"]   == "review"
            assert entry["resolver"] == "manual_required"
