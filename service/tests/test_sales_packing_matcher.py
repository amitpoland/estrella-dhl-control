"""test_sales_packing_matcher.py — PR-3 Sales Packing Matcher.

The matcher persists the canonical product_code (minted by
store_invoice_lines, copied into purchase packing_lines by
match_packing_to_invoice) into sales_packing_lines via a
batch-scoped lookup.

Architectural rules verified:
  * product_code is COPIED, never invented.
  * design_no NEVER becomes product_code.
  * Cross-batch design collisions cannot leak.
  * Ambiguous and unresolved designs leave product_code='' (DB layer
    continues to skip them).
  * PR #192 draft-sync resolver becomes a no-op once the matcher has
    persisted product_code at the row level.
  * No external HTTP / wFirma / SMTP / DHL calls.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    return tmp_path


@pytest.fixture()
def client(fresh):
    tmp = fresh
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@local"}
    yield TestClient(app), tmp
    app.dependency_overrides.clear()


def _seed_packing_pairs(tmp: Path, batch_id: str,
                        pairs: List[tuple]) -> None:
    """Seed packing.db with (design_no, product_code) rows."""
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


# ── 1. one-to-one resolution ──────────────────────────────────────────────

def test_resolves_via_same_batch_packing_lines_one_to_one(fresh):
    tmp = fresh
    bid = "B-RES"
    _seed_packing_pairs(tmp, bid, [("D-001", "PC-001")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "", "design_no": "D-001",
             "quantity": 1.0, "unit_price": 10.0, "currency": "USD"}]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert matched[0]["product_code"] == "PC-001"
    assert matched[0]["resolution_source"] == "batch_packing_lines"
    assert summary["designs_resolved"] == {"D-001": "PC-001"}
    assert summary["rows_resolved"] == 1
    assert summary["rows_total"] == 1


# ── 2. ambiguous design ───────────────────────────────────────────────────

def test_ambiguous_design_stays_empty_and_reports_candidates(fresh):
    tmp = fresh
    bid = "B-AMB"
    _seed_packing_pairs(tmp, bid,
                        [("PND", "PC-A"), ("PND", "PC-B")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "", "design_no": "PND",
             "quantity": 1, "unit_price": 1, "currency": "EUR"}]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert matched[0].get("product_code", "") == ""
    assert "resolution_source" not in matched[0]
    assert summary["designs_ambiguous"]["PND"] == ["PC-A", "PC-B"]
    assert summary["rows_skipped"] == 1


# ── 3. unresolved design ──────────────────────────────────────────────────

def test_unresolved_design_stays_empty(fresh):
    tmp = fresh
    bid = "B-UNR"
    _seed_packing_pairs(tmp, bid, [])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "", "design_no": "GHOST",
             "quantity": 1, "unit_price": 1, "currency": "USD"}]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert matched[0].get("product_code", "") == ""
    assert summary["designs_unresolved"] == ["GHOST"]


# ── 4. existing product_code wins ─────────────────────────────────────────

def test_existing_product_code_preserved(fresh):
    tmp = fresh
    bid = "B-KEEP"
    # The batch would map D-K → PC-WRONG, but the sales row already
    # has PC-RIGHT and must NOT be overwritten.
    _seed_packing_pairs(tmp, bid, [("D-K", "PC-WRONG")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "PC-RIGHT", "design_no": "D-K",
             "quantity": 1, "unit_price": 1, "currency": "USD"}]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert matched[0]["product_code"] == "PC-RIGHT"
    assert "resolution_source" not in matched[0]
    assert summary["rows_kept_pc"] == 1
    assert "D-K" not in summary["designs_resolved"]


# ── 5. cross-batch collision guard ────────────────────────────────────────

def test_resolution_is_strictly_batch_scoped(fresh):
    """Two batches each have (D-X, ...) but with DIFFERENT product_codes.
    Resolving for batch B must never see batch A's mapping."""
    tmp = fresh
    _seed_packing_pairs(tmp, "BATCH-A", [("D-X", "PC-FROM-A")])
    _seed_packing_pairs(tmp, "BATCH-B", [("D-X", "PC-FROM-B")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "", "design_no": "D-X",
             "quantity": 1, "unit_price": 1, "currency": "USD"}]
    _, sa = match_sales_lines_to_packing("BATCH-A", rows)
    _, sb = match_sales_lines_to_packing("BATCH-B", rows)
    assert sa["designs_resolved"] == {"D-X": "PC-FROM-A"}
    assert sb["designs_resolved"] == {"D-X": "PC-FROM-B"}


# ── 6. PR #192 resolver becomes a no-op when matcher persists pc ──────────

def test_pr192_resolver_is_noop_when_pc_already_present(fresh):
    """After PR-3 persists product_code on a row, PR #192's
    proforma_draft_sync.resolve_sales_lines_for_batch must short-
    circuit in its existing-wins branch."""
    tmp = fresh
    bid = "B-NOOP"
    _seed_packing_pairs(tmp, bid, [("D-N", "PC-N")])

    from app.services.sales_packing_matcher import match_sales_lines_to_packing
    from app.services.proforma_draft_sync import resolve_sales_lines_for_batch

    rows = [{"product_code": "", "design_no": "D-N",
             "quantity": 1, "unit_price": 1, "currency": "USD"}]
    after_matcher, _ = match_sales_lines_to_packing(bid, rows)
    assert after_matcher[0]["product_code"] == "PC-N"

    # Now run PR #192 resolver on the same row — it should NOT
    # re-resolve (designs_resolved stays empty).
    after_resolver, summary = resolve_sales_lines_for_batch(
        bid, after_matcher,
    )
    assert after_resolver[0]["product_code"] == "PC-N"
    assert summary["designs_resolved"] == {}


# ── 7. matcher does NOT consume packing_lines (N:1) ───────────────────────

def test_matcher_does_not_consume_packing_lines(fresh):
    """A single purchase packing row may match many sales rows on
    the same design.  All sales rows must receive the same pc."""
    tmp = fresh
    bid = "B-N1"
    _seed_packing_pairs(tmp, bid, [("D-MANY", "PC-MANY")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [
        {"product_code": "", "design_no": "D-MANY", "quantity": 1},
        {"product_code": "", "design_no": "D-MANY", "quantity": 2},
        {"product_code": "", "design_no": "D-MANY", "quantity": 3},
    ]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert [r["product_code"] for r in matched] == ["PC-MANY"] * 3
    assert summary["rows_resolved"] == 3


# ── 8. NULL/empty purchase-side product_code ignored ──────────────────────

def test_null_or_empty_purchase_pc_is_not_a_candidate(fresh):
    tmp = fresh
    bid = "B-NULL"
    # Two packing rows for D-NULL — one with empty pc, one with valid.
    # The valid one must win 1-to-1; empty must not even appear as a
    # candidate.  A separate design with ONLY empty pc must yield
    # 0 candidates (unresolved).
    _seed_packing_pairs(tmp, bid, [
        ("D-VALID", ""),       # empty product_code — must be ignored
        ("D-VALID", "PC-V"),   # valid candidate
        ("D-ONLY-EMPTY", ""),  # only empty candidate
    ])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [
        {"product_code": "", "design_no": "D-VALID"},
        {"product_code": "", "design_no": "D-ONLY-EMPTY"},
    ]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert matched[0]["product_code"] == "PC-V"
    assert matched[1].get("product_code", "") == ""
    assert summary["designs_unresolved"] == ["D-ONLY-EMPTY"]


# ── 9. empty design_no short-circuits ─────────────────────────────────────

def test_empty_design_no_short_circuits(fresh):
    tmp = fresh
    bid = "B-EMPTY-DN"
    _seed_packing_pairs(tmp, bid, [("D-X", "PC-X")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "", "design_no": ""}]
    matched, summary = match_sales_lines_to_packing(bid, rows)
    assert matched[0].get("product_code", "") == ""
    assert summary["designs_unresolved"] == []
    assert summary["designs_ambiguous"] == {}
    assert summary["rows_skipped"] == 1


# ── 10. idempotent across repeat reprocess ────────────────────────────────

def test_repeat_match_is_idempotent(fresh):
    tmp = fresh
    bid = "B-IDEM"
    _seed_packing_pairs(tmp, bid, [("D-I", "PC-I")])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows1 = [{"product_code": "", "design_no": "D-I", "quantity": 1}]
    m1, _ = match_sales_lines_to_packing(bid, rows1)
    # Second pass on the just-matched rows triggers the existing-wins
    # branch — no resolution work needed.
    m2, summary2 = match_sales_lines_to_packing(bid, m1)
    assert m2[0]["product_code"] == "PC-I"
    assert summary2["designs_resolved"] == {}
    assert summary2["rows_kept_pc"] == 1


# ── 11. no external calls in matcher source ───────────────────────────────

def test_matcher_module_has_no_external_calls():
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "sales_packing_matcher.py").read_text(encoding="utf-8")
    for forbidden in ("requests.", "httpx.", "wfirma_client",
                      "smtp", "send_email", "dhl_dispatch"):
        assert forbidden not in src, (
            f"sales_packing_matcher must not reference {forbidden!r}"
        )
    # Operational sales matcher must NOT consult the global advisory
    # bridge — cross-batch leakage risk.
    assert "design_product_bridge" not in src, (
        "operational sales matcher must NOT consult the global "
        "design_product_bridge — would leak cross-batch collisions"
    )
    assert "get_product_codes_for_design" not in src


# ── 12. design_no never becomes product_code ──────────────────────────────

def test_design_no_never_becomes_product_code(fresh):
    """Architectural invariant — under no condition does the matcher
    use design_no as a product_code fallback."""
    tmp = fresh
    bid = "B-NEVER"
    _seed_packing_pairs(tmp, bid, [])   # no purchase evidence
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    rows = [{"product_code": "", "design_no": "D-NEVER"}]
    matched, _ = match_sales_lines_to_packing(bid, rows)
    assert matched[0].get("product_code", "") == "", (
        "design_no must NEVER be assigned as product_code"
    )

    # Source-grep guard — no string pattern that would create that
    # fallback in the matcher module.
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "sales_packing_matcher.py").read_text(encoding="utf-8")
    for bad in ('= design_no', 'or design_no', '= dn', 'or dn'):
        # Note: the matcher does use `dn = ...get("design_no")` as a
        # local var name, so we look for the *assignment to
        # product_code* not the variable itself.
        pass
    # Tighter check: no "product_code" = "design" pattern.
    forbid_patterns = [
        '"product_code": design_no',
        'product_code = design_no',
        'product_code = dn',
        "product_code = r.get(\"design_no\")",
    ]
    for p in forbid_patterns:
        assert p not in src, f"matcher must not invent pc from design_no: {p!r}"


# ── 13. FastAPI end-to-end via reprocess endpoint ─────────────────────────

def test_reprocess_endpoint_populates_sales_pc(client, monkeypatch):
    cli, tmp = client
    bid = "B-E2E"

    # Seed purchase packing pair: design D-77 → product PC-77.
    _seed_packing_pairs(tmp, bid, [("D-77", "PC-77")])

    # Sales-side: register the sales packing list shipment_doc + sales
    # document, with a stub file on disk so reprocess accepts it.
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"batch_id": bid, "timeline": []}), encoding="utf-8",
    )
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    sid = ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="sales.xlsx", file_path=str(out / "sales.xlsx"),
        file_hash="h-e2e", source="intake",
    )
    ddb.store_sales_document(
        batch_id=bid, document_id=sid,
        data={"client_name": "ACME", "client_ref": "",
              "document_type": "sales_packing_list",
              "source_file_path": str(out / "sales.xlsx"),
              "extraction_status": "extracted"},
    )
    (out / "sales.xlsx").write_bytes(b"stub")

    # Patch the parser to emit one row with design_no but no pc.
    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: (
            [{"design_no": "D-77", "quantity": 2.0,
              "unit_price": 50.0, "currency": "USD"}],
            "fake", "1.0", {"failure_reason": None},
        ),
    )

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200, r.text
    body = r.json()

    # Matcher summary surfaced on the per-file response.
    file_entry = next(f for f in body["files"]
                      if f["document_type"] == "sales_packing_list")
    s = file_entry.get("sales_matcher_summary")
    assert s is not None, "sales_matcher_summary missing from response"
    assert s["designs_resolved"] == {"D-77": "PC-77"}

    # sales_packing_lines now carries the canonical product_code.
    rows = ddb.get_sales_packing_lines(bid)
    assert rows
    assert all(rec["product_code"] == "PC-77" for rec in rows), (
        f"sales_packing_lines.product_code not populated: "
        f"{[rec['product_code'] for rec in rows]}"
    )


# ── 14. response includes matcher summary buckets ─────────────────────────

def test_reprocess_response_includes_matcher_buckets(client, monkeypatch):
    cli, tmp = client
    bid = "B-BUCKETS"

    # Seed three behaviours: resolved, ambiguous, unresolved.
    _seed_packing_pairs(tmp, bid, [
        ("D-OK",   "PC-OK"),
        ("D-AMB",  "PC-A"),
        ("D-AMB",  "PC-B"),
    ])
    out = tmp / "outputs" / bid
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"batch_id": bid, "timeline": []}), encoding="utf-8",
    )
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    sid = ddb.register_document(
        batch_id=bid, document_type="sales_packing_list",
        file_name="s.xlsx", file_path=str(out / "s.xlsx"),
        file_hash="h-bk", source="intake",
    )
    ddb.store_sales_document(
        batch_id=bid, document_id=sid,
        data={"client_name": "ACME", "client_ref": "",
              "document_type": "sales_packing_list",
              "source_file_path": str(out / "s.xlsx"),
              "extraction_status": "extracted"},
    )
    (out / "s.xlsx").write_bytes(b"stub")

    from app.services import invoice_packing_extractor as ipe
    monkeypatch.setattr(
        ipe, "extract_packing",
        lambda p: (
            [
                {"design_no": "D-OK",    "quantity": 1, "unit_price": 1, "currency": "USD"},
                {"design_no": "D-AMB",   "quantity": 1, "unit_price": 1, "currency": "USD"},
                {"design_no": "D-GHOST", "quantity": 1, "unit_price": 1, "currency": "USD"},
            ],
            "fake", "1.0", {"failure_reason": None},
        ),
    )

    r = cli.post(f"/api/v1/packing/{bid}/reprocess")
    assert r.status_code == 200
    body = r.json()
    file_entry = next(f for f in body["files"]
                      if f["document_type"] == "sales_packing_list")
    s = file_entry["sales_matcher_summary"]
    assert s["designs_resolved"]   == {"D-OK": "PC-OK"}
    assert s["designs_ambiguous"]  == {"D-AMB": ["PC-A", "PC-B"]}
    assert s["designs_unresolved"] == ["D-GHOST"]
    assert s["rows_resolved"] == 1
    assert s["rows_skipped"]  == 2


# ── 15. metal/color disambiguation (Fix 2) ────────────────────────────────

def _seed_packing_with_metal(tmp: Path, batch_id: str,
                              rows: List[Dict[str, Any]]) -> None:
    """Seed packing_lines with full metal/metal_color fields."""
    from app.services import packing_db as pdb
    pdb.init_packing_db(tmp / "packing.db")
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id, document_id=f"pd2-{batch_id}",
        source_file_path="/tmp/p2.xlsx", invoice_no="INV2",
        parser_name="t", parser_version="1",
        source_file_hash=f"h2-{batch_id}",
    )
    lines = []
    for i, row in enumerate(rows):
        lines.append({
            "packing_document_id": doc_id, "batch_id": batch_id,
            "invoice_no": "INV2", "invoice_line_position": i,
            "product_code":  row.get("product_code", ""),
            "design_no":     row.get("design_no", ""),
            "metal":         row.get("metal", ""),
            "metal_color":   row.get("metal_color", ""),
            "quality_string": row.get("quality_string", ""),
            "batch_no": "", "bag_id": "", "tray_id": "",
            "item_type": "", "uom": "PCS",
            "quantity": 1.0, "gross_weight": 0, "net_weight": 0,
            "karat": "", "stone_type": "", "remarks": "",
            "extracted_confidence": 1.0, "requires_manual_review": False,
            "pack_sr": i, "unit_price": 0.0, "total_value": 0.0,
        })
    pdb.upsert_packing_lines(lines)


def test_metal_color_disambiguates_same_design_two_variants(fresh):
    """
    Same design_no appears twice with different metal/metal_color →
    different product_codes.  Sales rows with metal+color must resolve
    to the correct product_code via secondary (design, metal, color) key.
    """
    tmp = fresh
    bid = "B-METAL"
    _seed_packing_with_metal(tmp, bid, [
        {"design_no": "J4007R", "metal": "18KT", "metal_color": "Y", "product_code": "257-2"},
        {"design_no": "J4007R", "metal": "PT950", "metal_color": "",  "product_code": "257-4"},
    ])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    sales = [
        {"product_code": "", "design_no": "J4007R",
         "metal": "18KT", "metal_color": "Y", "quantity": 1},
        {"product_code": "", "design_no": "J4007R",
         "metal": "PT950", "metal_color": "", "quantity": 1},
    ]
    matched, summary = match_sales_lines_to_packing(bid, sales)
    assert matched[0]["product_code"] == "257-2", (
        "18KT Y variant should resolve to 257-2"
    )
    assert matched[0]["resolution_source"] == "batch_packing_lines_metal"
    assert matched[1]["product_code"] == "257-4", (
        "PT950 variant should resolve to 257-4"
    )
    assert matched[1]["resolution_source"] == "batch_packing_lines_metal"
    assert summary["rows_resolved"] == 2
    assert summary["rows_skipped"] == 0


def test_metal_disambiguation_still_skips_when_triple_also_ambiguous(fresh):
    """
    If even the (design, metal, color) triple is not unique in packing_lines
    (same metal+color, two product_codes), leave product_code empty.
    """
    tmp = fresh
    bid = "B-METAL-AMB"
    _seed_packing_with_metal(tmp, bid, [
        {"design_no": "D-TWIN", "metal": "14KT", "metal_color": "W", "product_code": "PC-X"},
        {"design_no": "D-TWIN", "metal": "14KT", "metal_color": "W", "product_code": "PC-Y"},
    ])
    from app.services.sales_packing_matcher import match_sales_lines_to_packing

    sales = [{"product_code": "", "design_no": "D-TWIN",
              "metal": "14KT", "metal_color": "W", "quantity": 1}]
    matched, summary = match_sales_lines_to_packing(bid, sales)
    assert matched[0].get("product_code", "") == "", (
        "Ambiguous triple should leave product_code empty"
    )
    assert summary["rows_skipped"] == 1
