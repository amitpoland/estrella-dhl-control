"""
test_agency_email_builder.py — B1 (agency_email_builder.build_agency_package)
recipient layout regression tests.

Spec docs/dhl_clearance_paths.md hard rule 7: agency recipient layout
identical for B1 and B4. TO = piotr + ciagarlak; CC = biuro + roman +
Estrella internal. Phase 0.3's CC-uniqueness intent (which lived on
the dead _build_agency_clearance_email path) is preserved here on the
LIVE B1 builder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
    return S()


def _seed_b1_audit(tmp_path: Path, batch_id: str = "B_B1_1",
                   awb: str = "1012178215") -> dict:
    """Minimal valid audit for B1 build_agency_package: agency path, Polish
    description on disk, invoice + AWB PDFs present."""
    batch_dir = tmp_path / "outputs" / batch_id
    awb_dir   = batch_dir / "source" / "awb"
    inv_dir   = batch_dir / "source" / "invoices"
    polish_dir = tmp_path / "polish_descriptions"
    for d in (awb_dir, inv_dir, polish_dir):
        d.mkdir(parents=True, exist_ok=True)

    polish_fn = "desc_PL.pdf"
    (polish_dir / polish_fn).write_bytes(b"%PDF polish")
    (inv_dir / "INV.pdf").write_bytes(b"%PDF inv")
    awb_fn = f"{awb} AWB.pdf"
    (awb_dir / awb_fn).write_bytes(b"%PDF awb")

    return {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "doc_no":      "PZ_TEST",
        "polish_desc_filename": polish_fn,
        "inputs":      {"awb": awb_fn},
        "clearance_decision": {
            "total_value_usd":  10366.0,
            "clearance_path":   "agency_clearance",
        },
    }


# ── Spec v3 hard rule 7 — TO contains piotr + ciagarlak ────────────────────

def test_b1_to_contains_piotr_and_ganther(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.agency_email_builder.settings", _settings(tmp_path),
    )
    audit = _seed_b1_audit(tmp_path)
    from app.services.agency_email_builder import build_agency_package
    pkg = build_agency_package(audit, audit["batch_id"])

    assert "piotr@acspedycja.pl" in pkg["to_list"]
    assert "ciagarlak@ganther.com.pl" in pkg["to_list"]


def test_b1_cc_excludes_ganther(tmp_path, monkeypatch):
    """Ganther moved from CC to TO per spec v3. CC must not contain it."""
    monkeypatch.setattr(
        "app.services.agency_email_builder.settings", _settings(tmp_path),
    )
    audit = _seed_b1_audit(tmp_path)
    from app.services.agency_email_builder import build_agency_package
    pkg = build_agency_package(audit, audit["batch_id"])

    assert "ciagarlak@ganther.com.pl" not in pkg["cc_list"]


def test_b1_cc_contains_biuro_roman_and_internal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.agency_email_builder.settings", _settings(tmp_path),
    )
    audit = _seed_b1_audit(tmp_path)
    from app.services.agency_email_builder import build_agency_package
    pkg = build_agency_package(audit, audit["batch_id"])

    cc = pkg["cc_list"]
    assert "biuro@acspedycja.pl"        in cc
    assert "roman@acspedycja.pl"        in cc
    assert "info@estrellajewels.eu"     in cc
    assert "import@estrellajewels.eu"   in cc
    assert "account@estrellajewels.eu"  in cc


# ── CC-uniqueness regression (preserves Phase 0.3 intent on live builder) ──

def test_b1_recipient_uniqueness_no_dupes_no_overlap(tmp_path, monkeypatch):
    """Every TO and CC address appears exactly once; no address appears
    in both TO and CC simultaneously."""
    monkeypatch.setattr(
        "app.services.agency_email_builder.settings", _settings(tmp_path),
    )
    audit = _seed_b1_audit(tmp_path)
    from app.services.agency_email_builder import build_agency_package
    pkg = build_agency_package(audit, audit["batch_id"])

    to_list = pkg["to_list"]
    cc_list = pkg["cc_list"]

    # Each TO address appears exactly once
    for addr in to_list:
        assert to_list.count(addr) == 1, f"TO duplicate: {addr}"

    # Each CC address appears exactly once
    for addr in cc_list:
        assert cc_list.count(addr) == 1, f"CC duplicate: {addr}"

    # No address in both TO and CC
    to_norm = {a.lower() for a in to_list}
    cc_norm = {a.lower() for a in cc_list}
    overlap = to_norm & cc_norm
    assert not overlap, f"address in both TO and CC: {overlap}"


# ── Spec rule 7 cross-check: B1 TO matches B4 TO; B1 CC matches B4 CC ──────

def test_b1_recipient_layout_matches_b4(tmp_path, monkeypatch):
    """Hard rule 7: agency recipient layout identical for B1 and B4."""
    monkeypatch.setattr(
        "app.services.agency_email_builder.settings", _settings(tmp_path),
    )
    monkeypatch.setattr(
        "app.services.agency_forward_after_dhl_builder.settings",
        _settings(tmp_path),
    )
    audit = _seed_b1_audit(tmp_path)
    # Add the B4 prerequisites onto the same audit
    audit["dhl_email"] = {"received": True, "ticket": "T#TEST"}
    audit["dhl_documents_received"] = {"received": True, "files": []}

    from app.services.agency_email_builder import build_agency_package
    from app.services.agency_forward_after_dhl_builder import (
        build_agency_forward_after_dhl,
    )

    b1 = build_agency_package(audit, audit["batch_id"])
    b4 = build_agency_forward_after_dhl(audit, audit["batch_id"])

    assert b1["to_list"] == b4["to_list"]
    assert sorted(b1["cc_list"]) == sorted(b4["cc_list"])


# ── Spec rule 7 (extended) — follow-up reminders match B1/B4 layout ────────

def test_agency_followup_recipient_layout_matches_b1(tmp_path, monkeypatch):
    """Hard rule 7 (extended): agency follow-up reminders share the
    B1/B4 recipient layout. TO = Piotr + Ganther; CC = biuro + roman +
    Estrella internal. Pins the action_email_builder dispatcher path
    that operators trigger via /api/v1/lifecycle/agency-followup."""
    monkeypatch.setattr(
        "app.services.agency_email_builder.settings", _settings(tmp_path),
    )
    audit = _seed_b1_audit(tmp_path)

    from app.services.agency_email_builder import build_agency_package
    from app.services.action_email_builder import build_email_draft

    b1 = build_agency_package(audit, audit["batch_id"])
    followup = build_email_draft("agency_followup", audit)

    # build_agency_package returns "to" as comma-joined string;
    # build_email_draft also returns "to" as a string. Compare directly.
    assert b1["to"] == followup["to"]
    # CC strings: split on commas, normalize whitespace, sort, compare.
    b1_cc = sorted(a.strip() for a in b1["cc"].split(",") if a.strip())
    fu_cc = sorted(a.strip() for a in followup["cc"].split(",") if a.strip())
    assert b1_cc == fu_cc

    # Belt-and-braces: explicit recipient invariants.
    assert "piotr@acspedycja.pl"      in followup["to"]
    assert "ciagarlak@ganther.com.pl" in followup["to"]
    assert "ciagarlak@ganther.com.pl" not in followup["cc"]
