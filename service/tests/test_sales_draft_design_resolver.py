"""test_sales_draft_design_resolver.py — batch-scoped product_code
resolution for sales draft sync.

The resolver fills in ``sales_packing_lines.product_code`` from same-batch
purchase ``packing_lines`` evidence ONLY.  Cross-batch design collisions
must never leak.  The global design_product_mapping registry is
advisory and is NOT consulted in the operational draft-sync path.

DB-layer invariant (proforma_invoice_link_db.py) — rows with empty
product_code are still skipped at create/reset time — must remain
intact.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    return tmp_path


def _seed_packing_pair(tmp: Path, batch_id: str, pairs: List[tuple]) -> None:
    """Seed packing.db with (design_no, product_code) pairs for batch."""
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp / "packing.db")
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id, document_id=f"pd-{batch_id}",
        source_file_path="/tmp/p.xlsx", invoice_no="INV",
        parser_name="t", parser_version="1",
        source_file_hash=f"h-{batch_id}",
    )
    lines = []
    for i, (design, product) in enumerate(pairs):
        lines.append({
            "packing_document_id": doc_id, "batch_id": batch_id,
            "invoice_no": "INV", "invoice_line_position": i,
            "product_code": product, "design_no": design,
            "batch_no": "", "bag_id": "", "tray_id": "",
            "item_type": "", "uom": "PCS",
            "quantity": 1.0, "gross_weight": 0, "net_weight": 0,
            "metal": "", "karat": "", "stone_type": "", "remarks": "",
            "extracted_confidence": 1.0, "requires_manual_review": False,
            "pack_sr": i, "unit_price": 0.0, "total_value": 0.0,
        })
    pdb.upsert_packing_lines(lines)


# ── 1. Resolution with exactly 1 candidate ────────────────────────────────

def test_resolves_product_code_via_batch_lookup(setup):
    tmp = setup
    bid = "B-RESOLVE"
    _seed_packing_pair(tmp, bid, [("D-001", "PC-001")])

    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
    rows = [{"product_code": "", "design_no": "D-001",
             "qty": 1, "unit_price": 10.0, "currency": "USD"}]
    resolved, summary = resolve_sales_lines_for_batch(bid, rows)

    assert len(resolved) == 1
    assert resolved[0]["product_code"] == "PC-001"
    assert resolved[0]["resolution_source"] == "batch_packing_lines"
    assert summary["designs_resolved"] == {"D-001": "PC-001"}
    assert summary["designs_ambiguous"] == {}
    assert summary["designs_unresolved"] == []


# ── 2. Ambiguous design — multiple candidates → skip ──────────────────────

def test_ambiguous_design_skipped_and_reported(setup):
    tmp = setup
    bid = "B-AMBIG"
    _seed_packing_pair(tmp, bid, [("PND", "PC-A"), ("PND", "PC-B")])

    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
    rows = [{"product_code": "", "design_no": "PND",
             "qty": 1, "unit_price": 5.0, "currency": "EUR"}]
    resolved, summary = resolve_sales_lines_for_batch(bid, rows)

    assert resolved[0].get("product_code", "") == ""
    assert "resolution_source" not in resolved[0]
    assert summary["designs_ambiguous"]["PND"] == ["PC-A", "PC-B"]
    assert summary["designs_resolved"] == {}


# ── 3. Unresolvable design — zero candidates → skip ───────────────────────

def test_unresolvable_design_skipped_and_reported(setup):
    tmp = setup
    bid = "B-UNRES"
    _seed_packing_pair(tmp, bid, [])  # no purchase rows

    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
    rows = [{"product_code": "", "design_no": "GHOST",
             "qty": 1, "unit_price": 1.0, "currency": "USD"}]
    resolved, summary = resolve_sales_lines_for_batch(bid, rows)

    assert resolved[0].get("product_code", "") == ""
    assert summary["designs_unresolved"] == ["GHOST"]
    assert summary["designs_resolved"] == {}


# ── 4. Existing product_code wins — never overwritten ─────────────────────

def test_existing_product_code_is_preserved(setup):
    tmp = setup
    bid = "B-PRESERVE"
    # The bridge would map D-1 -> PC-WRONG, but the sales row already
    # carries PC-RIGHT and must NOT be overwritten.
    _seed_packing_pair(tmp, bid, [("D-1", "PC-WRONG")])

    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
    rows = [{"product_code": "PC-RIGHT", "design_no": "D-1",
             "qty": 1, "unit_price": 9.0, "currency": "USD"}]
    resolved, summary = resolve_sales_lines_for_batch(bid, rows)

    assert resolved[0]["product_code"] == "PC-RIGHT"
    # No "resolution_source" added — row passed through unchanged.
    assert "resolution_source" not in resolved[0]
    # Resolver did not record this design under any summary bucket.
    assert "D-1" not in summary["designs_resolved"]
    assert "D-1" not in summary["designs_ambiguous"]


# ── 5. Cross-batch collision guard ────────────────────────────────────────

def test_resolution_is_strictly_batch_scoped(setup):
    """Two batches each have (D-X, ...) but with DIFFERENT product_codes.
    Resolving for batch B must never see batch A's pair."""
    tmp = setup
    _seed_packing_pair(tmp, "BATCH-A", [("D-X", "PC-FROM-A")])
    _seed_packing_pair(tmp, "BATCH-B", [("D-X", "PC-FROM-B")])

    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
    rows = [{"product_code": "", "design_no": "D-X",
             "qty": 1, "unit_price": 1.0, "currency": "USD"}]

    resolved_a, summary_a = resolve_sales_lines_for_batch("BATCH-A", rows)
    resolved_b, summary_b = resolve_sales_lines_for_batch("BATCH-B", rows)

    assert resolved_a[0]["product_code"] == "PC-FROM-A"
    assert resolved_b[0]["product_code"] == "PC-FROM-B"
    # Crucially: neither resolver returned the OTHER batch's product_code.
    assert summary_a["designs_resolved"] == {"D-X": "PC-FROM-A"}
    assert summary_b["designs_resolved"] == {"D-X": "PC-FROM-B"}


# ── 6. NULL product_code on purchase side is ignored ──────────────────────

def test_null_product_code_on_purchase_side_is_not_a_candidate(setup):
    """packing_lines rows with NULL/empty product_code must NOT be
    counted as a candidate (would otherwise become a false positive)."""
    tmp = setup
    bid = "B-NULL-PC"
    _seed_packing_pair(tmp, bid, [("D-NULL", "")])
    # No real pairs — only a row with empty product_code.

    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch
    rows = [{"product_code": "", "design_no": "D-NULL",
             "qty": 1, "unit_price": 1.0, "currency": "USD"}]
    resolved, summary = resolve_sales_lines_for_batch(bid, rows)

    assert resolved[0].get("product_code", "") == ""
    assert summary["designs_unresolved"] == ["D-NULL"]


# ── 7. DB-layer invariant preserved when called directly ──────────────────

def test_db_layer_still_skips_empty_product_code(setup):
    """Regression guard for the invariant in proforma_invoice_link_db.py:
    rows passed in with empty product_code must still be skipped by the
    DB-layer helper, independent of any upstream resolver."""
    tmp = setup
    bid = "B-INV"
    from app.services import proforma_invoice_link_db as pildb
    pildb.init_db(tmp / "proforma_links.db")
    draft, was_created = pildb.auto_create_draft_from_sales_packing(
        tmp / "proforma_links.db",
        batch_id=bid, client_name="ACME", currency="USD",
        lines=[
            {"product_code": "", "design_no": "D-X", "qty": 1, "unit_price": 1},
            {"product_code": "PC-1", "design_no": "D-1", "qty": 2, "unit_price": 2},
        ],
        operator="t",
    )
    assert was_created
    import json
    parsed = json.loads(draft.editable_lines_json or "[]")
    pcs = [ln.get("product_code") for ln in parsed]
    assert pcs == ["PC-1"], (
        f"DB layer must skip empty product_code; got pcs={pcs}"
    )


# ── 8. Sync end-to-end: empty product_code gets resolved + draft has lines

def test_sync_resolves_and_creates_draft_with_lines(setup, monkeypatch):
    """End-to-end: sales_packing_lines with empty product_code +
    matching design_no in packing_lines → draft created with the
    resolved product_code line."""
    tmp = setup
    bid = "B-E2E"

    # Purchase side: design D-77 → product PC-77.
    _seed_packing_pair(tmp, bid, [("D-77", "PC-77")])

    # Sales side: row with empty product_code but design_no = D-77.
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    sid = ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="s.xlsx", file_path="/tmp/s.xlsx",
        file_hash="hh", source="intake",
    )
    ddb.store_sales_document(
        batch_id=bid, document_id=sid,
        data={"client_name": "ACME", "client_ref": "",
              "document_type": "sales_packing_list",
              "source_file_path": "/tmp/s.xlsx",
              "extraction_status": "extracted"},
    )
    ddb.store_sales_packing_lines(
        sales_document_id=sid, batch_id=bid,
        lines=[{"client_name": "ACME", "client_ref": "",
                "product_code": "", "design_no": "D-77",
                "bag_id": "", "quantity": 3.0, "remarks": "",
                "unit_price": 50.0, "currency": "USD", "total_value": 150.0}],
    )

    from app.services.proforma_draft_sync import sync_draft_from_packing_upload
    result = sync_draft_from_packing_upload(
        batch_id=bid, operator="tester",
        db_path=tmp / "proforma_links.db",
    )
    assert result["clients_processed"] == 1
    assert result["created"] == 1
    assert result["designs_resolved"] == {"D-77": "PC-77"}

    # Confirm draft has the resolved line.
    from app.services import proforma_invoice_link_db as pildb
    drafts = pildb.list_drafts_for_batch(tmp / "proforma_links.db", bid)
    assert len(drafts) == 1
    import json
    lines = json.loads(drafts[0].editable_lines_json or "[]")
    assert len(lines) == 1
    assert lines[0]["product_code"] == "PC-77"
    assert lines[0]["design_no"] == "D-77"


# ── 9. Sync result includes empty buckets when no resolution work ─────────

def test_sync_result_keys_present_even_when_no_resolution_needed(setup):
    """designs_resolved/ambiguous/unresolved keys must always be present
    in the sync result, even when no rows needed resolution. This keeps
    downstream consumers (logging, dashboards, tests) safe."""
    tmp = setup
    bid = "B-EMPTY"

    from app.services.proforma_draft_sync import sync_draft_from_packing_upload
    result = sync_draft_from_packing_upload(
        batch_id=bid, operator="tester",
        db_path=tmp / "proforma_links.db",
    )
    # No sales_lines → short-circuit return; keys must still be present.
    for k in ("designs_resolved", "designs_ambiguous", "designs_unresolved"):
        assert k in result, f"sync result missing {k!r}"


# ── 10. No external HTTP / wFirma / SMTP calls in resolver module ─────────

def test_resolver_module_has_no_external_calls():
    """Source-grep guard — operational draft sync resolver must stay
    local-DB only."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "proforma_draft_sync.py").read_text(encoding="utf-8")
    for forbidden in ("requests.", "httpx.", "wfirma_client",
                      "smtp", "send_email", "dhl_dispatch"):
        assert forbidden not in src, (
            f"proforma_draft_sync.py must not reference {forbidden!r}"
        )
    # Operational resolver must NOT consult the global advisory bridge.
    assert "get_product_codes_for_design" not in src, (
        "operational sync must not consult the global design bridge — "
        "it would leak cross-batch design collisions"
    )
