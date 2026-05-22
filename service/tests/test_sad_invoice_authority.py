"""SAD invoice-reference authority — regression lock (2026-05-22).

Replaces free-text inference display with a structured authority object.
invoice_refs_method "inferred_from_sad_free_text" produces noise tokens like
['3322','121','088','2026','2027','585'] that must NEVER be shown as invoice
references. Only N935-derived references (e.g. "EJL/26-27/039") are authority.

These tests pin all four status values, the no-split invariant for invoice IDs,
and the source-grep for batch API injection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.sad_invoice_authority import derive_sad_invoice_authority

HTML    = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"
ROUTES  = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_dashboard.py"

# ── helpers ───────────────────────────────────────────────────────────────────

def _audit(*, method="N935", refs=None, match=None,
           parsed_invoice_nos=None, has_zc429=True):
    a: dict = {}
    if has_zc429:
        a["zc429"] = {
            "invoice_refs_method": method,
            "invoice_refs":        refs if refs is not None else ["EJL/26-27/039"],
            "inferred_refs":       ["3322", "121", "088", "2026", "2027"],
        }
    if match is not None or parsed_invoice_nos is not None:
        a["verification"] = {}
        if match is not None:
            a["verification"]["invoice_refs_match"] = match
        if parsed_invoice_nos is not None:
            a["verification"]["parsed_invoice_nos"] = parsed_invoice_nos
    return a


# ── 1. N935 match → matched_structured_n935 ──────────────────────────────────

def test_n935_match_returns_matched_structured_status():
    r = derive_sad_invoice_authority(_audit(method="N935", match=True,
                                           parsed_invoice_nos=["039"]))
    assert r["status"] == "matched_structured_n935"
    assert r["source"] == "n935"
    assert r["warning"] is None
    assert r["review_reason"] is None


# ── 2. N935 mismatch → n935_present_mismatch ─────────────────────────────────

def test_n935_mismatch_returns_mismatch_status():
    r = derive_sad_invoice_authority(_audit(method="N935", match=False,
                                           parsed_invoice_nos=["040"]))
    assert r["status"] == "n935_present_mismatch"
    assert r["source"] == "n935"
    assert r["warning"] is not None
    assert r["review_reason"] is not None


# ── 3. N935 present but match=None → unverified ───────────────────────────────

def test_n935_present_but_unverifiable_returns_unverified():
    r = derive_sad_invoice_authority(_audit(method="N935", match=None))
    assert r["status"] == "unverified_no_structured_reference"
    assert r["source"] == "n935"
    # Still carries the references (N935 was parsed)
    assert len(r["references"]) > 0


# ── 4. not_found → n935_absent ────────────────────────────────────────────────

def test_not_found_returns_n935_absent():
    r = derive_sad_invoice_authority(_audit(method="not_found", refs=[]))
    assert r["status"] == "n935_absent"
    assert r["source"] == "none"
    assert r["references"] == []
    assert r["warning"] is None


# ── 5. inferred method → unverified, no refs in authority ────────────────────

def test_inferred_method_returns_unverified_no_refs_in_authority():
    r = derive_sad_invoice_authority(_audit(method="inferred_from_sad_free_text"))
    assert r["status"] == "unverified_no_structured_reference"
    assert r["source"] == "advisory_text"
    assert r["references"] == [], "inferred_refs must not enter authority.references"


# ── 6. inferred_refs NEVER in authority.references ───────────────────────────

def test_inferred_refs_never_in_authority_references_list():
    """Garbage tokens like ['3322','121','088','2026','2027'] must be excluded."""
    r = derive_sad_invoice_authority(_audit(method="inferred_from_sad_free_text"))
    noise_tokens = {"3322", "121", "088", "2026", "2027", "585"}
    for ref in r["references"]:
        assert ref not in noise_tokens, (
            f"Noise token '{ref}' must not appear in authority references"
        )


# ── 7. Invoice ID preserved intact — not split ────────────────────────────────

def test_invoice_id_preserved_intact_not_split():
    """An N935 reference like 'EJL/26-27/039' or '088/2026-2027' must stay intact.
    It must never be split into ['EJL', '26', '27', '039'] or ['088','2026','2027']."""
    intact_ref = "EJL/26-27/039"
    r = derive_sad_invoice_authority(_audit(method="N935", refs=[intact_ref], match=True,
                                           parsed_invoice_nos=["039"]))
    assert intact_ref in r["references"], (
        f"Reference '{intact_ref}' must appear intact in authority.references"
    )
    # None of the split components should appear as separate references
    split_parts = {"EJL", "26", "27", "039", "26-27"}
    for part in split_parts:
        assert part not in r["references"], (
            f"Split component '{part}' must not appear as a separate reference"
        )


# ── 8. No zc429 → unverified with no refs ─────────────────────────────────────

def test_no_zc429_returns_unverified_with_no_refs():
    r = derive_sad_invoice_authority({})
    assert r["status"] == "unverified_no_structured_reference"
    assert r["references"] == []
    assert r["matched_invoice_ids"] == []
    assert "not yet processed" in (r["review_reason"] or "")


# ── 9. Authority injected in batch detail (source-grep) ───────────────────────

def test_authority_injected_in_batch_detail_source_grep():
    src = ROUTES.read_text(encoding="utf-8")
    assert "sad_invoice_authority" in src, (
        "routes_dashboard.py must inject sad_invoice_authority into batch response"
    )
    assert "derive_sad_invoice_authority" in src, (
        "routes_dashboard.py must call derive_sad_invoice_authority"
    )


# ── 10. Frontend renders from sad_invoice_authority (source-grep) ─────────────

def test_frontend_renders_from_authority_not_raw_inferred():
    src = HTML.read_text(encoding="utf-8")
    assert "sad_invoice_authority" in src, (
        "shipment-detail.html must reference audit.sad_invoice_authority"
    )
    assert 'data-testid="sad-invoice-authority-row"' in src, (
        "Authority display must have data-testid=sad-invoice-authority-row"
    )
    assert 'data-testid="sad-invoice-authority-status"' in src, (
        "Status span must have data-testid=sad-invoice-authority-status"
    )
    # The four status string literals must all be represented in the UI
    assert "matched_structured_n935" in src
    assert "n935_absent"             in src
    assert "n935_present_mismatch"   in src
    # Garbage token list must NOT appear in a display context
    assert "'3322'" not in src and '"3322"' not in src, (
        "Noise token '3322' must not be hardcoded in the UI"
    )
