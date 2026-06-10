"""test_dhl_description_db_injection.py — PR-206 row-injection + guard.

Covers:
  - DB-first row projection from documents.db invoice_lines
  - cross-batch shared-AWB union (4218922912 scenario: 9040dd39 audit
    only / bd18ec98 invoice_lines only)
  - canonical engine input shape preserved (description, unit_price,
    line_total, hsn_code, PCS/PRS UoM)
  - reconciliation (FOB drift, qty drift, missing-invoice)
  - 422 guard when no source has rows
  - 422 guard when reconciliation fails
  - no engine modification, no wFirma/PZ/DHL-email/post call paths added
"""
from __future__ import annotations

import json
import sqlite3 as _s
import uuid as _u
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path

import pytest


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """Per-test storage with documents.db initialised; module-level
    _db_path saved + restored so other suites aren't polluted."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.services import document_db as ddb
    saved = ddb._db_path
    ddb.init_document_db(tmp_path / "documents.db")
    try:
        yield tmp_path
    finally:
        ddb._db_path = saved


def _seed_invoice_line(tmp: Path, *, batch_id: str, invoice_no: str,
                       position: int, product_code: str,
                       description: str, qty: float, unit_price: float,
                       total: float, currency: str = "USD",
                       hsn_code: str = "71131913") -> None:
    now = _dt.now(_tz.utc).isoformat()
    with _s.connect(str(tmp / "documents.db")) as con:
        con.execute(
            "INSERT INTO invoice_lines "
            "(id, document_id, batch_id, invoice_no, line_position, "
            " product_code, description, quantity, unit_price, "
            " total_value, currency, hs_code, gross_weight, net_weight, "
            " rate_usd, amount_usd, hsn_code, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(_u.uuid4()), "doc-" + invoice_no + "-" + str(position),
                batch_id, invoice_no, position, product_code, description,
                qty, unit_price, total, currency, hsn_code, 0.0, 0.0,
                unit_price, total, hsn_code, now,
            ),
        )
        con.commit()


def _seed_shipment_doc(tmp: Path, *, batch_id: str, awb: str,
                       invoice_no: str) -> str:
    """Register a purchase_invoice doc tying batch_id ↔ awb."""
    from app.services import document_db as ddb
    fpath = tmp / f"inv-{batch_id}-{invoice_no.replace('/','-')}.pdf"
    fpath.write_bytes(b"fake")
    doc_id = ddb.register_document(
        batch_id=batch_id, document_type="purchase_invoice",
        file_name=fpath.name, file_path=str(fpath),
        file_hash=ddb.sha256_file(fpath),
        awb=awb, source="test",
    ) or ""
    return doc_id


def _seed_4218922912_world(tmp: Path) -> tuple[str, str, str]:
    """Reproduce the production dual-batch case for AWB 4218922912.

    bd18ec98: holds the real per-line invoice_lines for 4 invoices
              (177, 178, 179, 180) — 12 rows total, FOB $16,167.
    9040dd39: holds the audit-side aggregates (invoice_names + totals)
              but NO invoice_lines.

    The DHL generator is called on 9040dd39; it MUST pull rows from
    bd18ec98 via shared-AWB union.
    """
    awb        = "4218922912"
    batch_aud  = "SHIPMENT_4218922912_2026-05_9040dd39"
    batch_db   = "SHIPMENT_4218922912_2026-05_bd18ec98"
    # Shipment documents — both batches reference the same AWB.
    _seed_shipment_doc(tmp, batch_id=batch_aud, awb=awb, invoice_no="audit_only")
    for inv in ("EJL/26-27/177", "EJL/26-27/178",
                "EJL/26-27/179", "EJL/26-27/180"):
        _seed_shipment_doc(tmp, batch_id=batch_db, awb=awb, invoice_no=inv)
    # Real per-line invoice_lines — sums to 16167.00 USD, 46 units.
    seed_data = (
        # 177 × 5
        ("EJL/26-27/177", 1, "EJL/26-27/177-1",
         "PCS, 18KT Gold, Plain Jewellery RING",            3.0, 355.33, 1066.0, "71131911"),
        ("EJL/26-27/177", 2, "EJL/26-27/177-2",
         "PCS, 14KT Gold, Stud With Diam Jewel PENDANT",    4.0, 351.0,  1404.0, "71131913"),
        ("EJL/26-27/177", 3, "EJL/26-27/177-3",
         "PCS, 14KT Gold, Stud With Diam Jewel RING",       7.0, 326.0,  2282.0, "71131913"),
        ("EJL/26-27/177", 4, "EJL/26-27/177-4",
         "PCS, 18KT Gold, Stud With Diam Jewel RING",       4.0, 265.25, 1061.0, "71131913"),
        ("EJL/26-27/177", 5, "EJL/26-27/177-5",
         "PRS, 18KT Gold, Stud With Diam Jewel EARRINGS",  20.0,  93.6,  1872.0, "71131913"),
        # 178 × 1
        ("EJL/26-27/178", 1, "EJL/26-27/178-1",
         "PCS, 18KT Gold, Stud With Diam Jewel RING",       1.0, 211.0,   211.0, "71131913"),
        # 179 × 2
        ("EJL/26-27/179", 1, "EJL/26-27/179-1",
         "PCS, 18KT Gold, Plain Jewellery RING",            1.0, 796.0,   796.0, "71131911"),
        ("EJL/26-27/179", 2, "EJL/26-27/179-2",
         "PCS, 18KT Gold, Stud With Diam Jewel RING",       1.0, 1876.0, 1876.0, "71131913"),
        # 180 × 4
        ("EJL/26-27/180", 1, "EJL/26-27/180-1",
         "PCS, SL925 SILVER Studed Jewellery CLS PENDANT",  2.0, 1291.5, 2583.0, "71131145"),
        ("EJL/26-27/180", 2, "EJL/26-27/180-2",
         "PCS, 14KT Gold,Plain Jewellery BRACELET",         1.0, 1727.0, 1727.0, "71131911"),
        ("EJL/26-27/180", 3, "EJL/26-27/180-3",
         "PCS, 14KT Gold,Plain Jewellery PENDANT",          1.0,  602.0,  602.0, "71131911"),
        ("EJL/26-27/180", 4, "EJL/26-27/180-4",
         "PCS, 14KT Gold,Plain Jewellery RING",             1.0,  687.0,  687.0, "71131911"),
    )
    for inv_no, pos, pc, desc, qty, up, lt, hsn in seed_data:
        _seed_invoice_line(
            tmp, batch_id=batch_db, invoice_no=inv_no, position=pos,
            product_code=pc, description=desc, qty=qty,
            unit_price=up, total=lt, hsn_code=hsn,
        )
    return awb, batch_aud, batch_db


def _audit_4218922912(awb: str, batch_aud: str) -> dict:
    return {
        "awb":     awb,
        "dhl_awb": awb,
        "batch_id": batch_aud,
        "invoice_names": [
            "Invoice EJL-26-27-179-16-05-26.pdf",
            "Invoice EJL-26-27-178-16-05-26.pdf",
            "Invoice EJL-26-27-177-16-05-26.pdf",
            "Invoice EJL-26-27-180-16-05-26.pdf",
        ],
        "invoice_totals": {
            "total_pcs":       26,
            "total_prs":       20,
            "total_units":     46,
            "total_fob_usd":   16167.0,
            "total_freight_usd":   95.0,
            "total_insurance_usd": 55.0,
            "total_cif_usd":   16317.0,
            "product_counts": {
                "rings": 18, "pendants": 7, "bracelets": 1, "earrings": 20,
                "necklaces": 0, "cufflinks": 0, "other_jewellery": 0,
            },
            "product_counts_by_unit": {
                "PCS": {"rings": 18, "pendants": 7, "bracelets": 1},
                "PRS": {"earrings": 20},
            },
        },
    }


# ── 1. Primary path: DB rows for THIS batch ────────────────────────────

def test_db_invoice_lines_inject_for_same_batch(fresh):
    from app.api import routes_dhl_clearance as rdc
    # Seed only the DB-side batch with rows + use the same batch as audit.
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = {"awb": awb, "batch_id": batch_db}
    out = rdc._inject_rows_from_db_invoice_lines(batch_db, audit)
    assert out["_rows_source"] == "db_invoice_lines"
    rows = out["rows"]
    assert len(rows) == 12, [r.get("invoice_number") for r in rows]
    invs = sorted({r["invoice_number"] for r in rows})
    assert invs == ["EJL/26-27/177", "EJL/26-27/178",
                    "EJL/26-27/179", "EJL/26-27/180"]


# ── 2. Cross-batch union: 9040dd39 has nothing, bd18ec98 has rows ──────

def test_db_invoice_lines_cross_batch_union_for_same_awb(fresh):
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = _audit_4218922912(awb, batch_aud)
    out = rdc._inject_rows_from_db_invoice_lines(batch_aud, audit)
    rows = out.get("rows") or []
    assert len(rows) == 12, "shared-AWB union must reach bd18ec98's 12 lines"
    assert out["_rows_source"] == "db_invoice_lines"
    invs = sorted({r["invoice_number"] for r in rows})
    assert invs == ["EJL/26-27/177", "EJL/26-27/178",
                    "EJL/26-27/179", "EJL/26-27/180"]


# ── 3. Per-line preservation (no averaging, real HSN, real description) ─

def test_db_inject_preserves_per_line_unit_price_and_hsn(fresh):
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = _audit_4218922912(awb, batch_aud)
    out = rdc._inject_rows_from_db_invoice_lines(batch_aud, audit)
    rows = out["rows"]
    by_pc = {r["product_code"]: r for r in rows}
    # Specific real per-line values must survive verbatim (no averaging).
    assert by_pc["EJL/26-27/180-2"]["unit_price"] == 1727.0
    assert by_pc["EJL/26-27/180-2"]["line_total"] == 1727.0
    assert by_pc["EJL/26-27/180-2"]["hsn_code"]   == "71131911"
    assert (by_pc["EJL/26-27/180-2"]["description"]
            == "PCS, 14KT Gold,Plain Jewellery BRACELET")
    # Silver line carries its own HSN — must not collapse to a single CN.
    assert by_pc["EJL/26-27/180-1"]["hsn_code"] == "71131145"


def test_db_inject_preserves_pcs_and_prs_uom(fresh):
    """EARRINGS line is PRS; everything else is PCS.  Both must survive."""
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    out = rdc._inject_rows_from_db_invoice_lines(
        batch_aud, _audit_4218922912(awb, batch_aud),
    )
    rows = out["rows"]
    by_pc = {r["product_code"]: r for r in rows}
    assert by_pc["EJL/26-27/177-5"]["uom"] == "PRS"   # EARRINGS pair
    assert by_pc["EJL/26-27/177-1"]["uom"] == "PCS"   # RING
    assert by_pc["EJL/26-27/180-2"]["uom"] == "PCS"   # BRACELET


# ── 4. Engine input shape — round-trip via _extract_invoices ────────────

def test_engine_round_trip_groups_rows_into_four_invoices(fresh, monkeypatch):
    """The engine's _extract_invoices reads `batch["rows"]` and groups by
    invoice_number into items.  Inject our DB rows, then call the engine
    function in isolation and assert the resulting per-invoice item list
    matches the seeded data."""
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = rdc._inject_rows_from_db_invoice_lines(
        batch_aud, _audit_4218922912(awb, batch_aud),
    )
    import sys as _sys
    from app.core.config import settings as _settings
    _engine_dir = str(_settings.engine_dir)
    if _engine_dir not in _sys.path:
        _sys.path.insert(0, _engine_dir)
    import customs_description_engine as _cde
    grouped = _cde._extract_invoices(audit)
    assert isinstance(grouped, list)
    by_inv = {g["invoice_number"]: g for g in grouped}
    assert set(by_inv.keys()) == {
        "EJL/26-27/177", "EJL/26-27/178",
        "EJL/26-27/179", "EJL/26-27/180",
    }
    assert len(by_inv["EJL/26-27/177"]["items"]) == 5
    assert len(by_inv["EJL/26-27/178"]["items"]) == 1
    assert len(by_inv["EJL/26-27/179"]["items"]) == 2
    assert len(by_inv["EJL/26-27/180"]["items"]) == 4


# ── 5. Idempotency: no-op when audit already has rows / invoices ───────

def test_inject_db_is_idempotent_when_rows_present(fresh):
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = _audit_4218922912(awb, batch_aud)
    audit["rows"] = [{"invoice_number": "PRE", "product_code": "PRE-1",
                      "description": "preset", "quantity": 1.0,
                      "unit_price": 100.0, "line_total": 100.0,
                      "hsn_code": "", "currency": "USD", "uom": "PCS"}]
    out = rdc._inject_rows_from_db_invoice_lines(batch_aud, audit)
    assert out["rows"] == audit["rows"], (
        "must not overwrite pre-populated rows"
    )


# ── 6. Reconciliation ──────────────────────────────────────────────────

def test_reconcile_ok_when_rows_match_audit_totals(fresh):
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = rdc._inject_rows_from_db_invoice_lines(
        batch_aud, _audit_4218922912(awb, batch_aud),
    )
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok"] is True, rep
    assert rep["warnings"] == []
    assert rep["details"]["row_count"] == 12
    assert rep["details"]["row_qty_total"] == 46
    assert abs(rep["details"]["fob_drift_usd"]) <= 1.00


def test_reconcile_blocks_when_invoice_missing_from_rows(fresh):
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = rdc._inject_rows_from_db_invoice_lines(
        batch_aud, _audit_4218922912(awb, batch_aud),
    )
    # Drop all rows for invoice 180 → reconciliation must flag missing.
    audit["rows"] = [r for r in audit["rows"]
                     if not r["invoice_number"].endswith("/180")]
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok"] is False
    assert any("invoices_missing_in_rows" in w for w in rep["warnings"])
    assert "180" in rep["details"]["missing_in_rows"]


def test_reconcile_blocks_on_fob_drift(fresh):
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = rdc._inject_rows_from_db_invoice_lines(
        batch_aud, _audit_4218922912(awb, batch_aud),
    )
    # Inflate one line's total by 1000 USD → drift > $1 → block.
    audit["rows"][0]["line_total"] += 1000.0
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok"] is False
    assert any(w.startswith("fob_total_drift") for w in rep["warnings"])


def test_reconcile_qty_drift_is_soft_when_fob_clean(fresh):
    # Qty drift with exact FOB is advisory-only — parser divergence noise.
    # ok_hard must be True (generation proceeds); ok strict is False.
    from app.api import routes_dhl_clearance as rdc
    awb, batch_aud, batch_db = _seed_4218922912_world(fresh)
    audit = rdc._inject_rows_from_db_invoice_lines(
        batch_aud, _audit_4218922912(awb, batch_aud),
    )
    audit["rows"][0]["quantity"] += 5.0
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok"] is False, "strict ok still False when qty drifts"
    assert rep["ok_hard"] is True, "ok_hard is True when only qty drifts with clean FOB"
    assert any(w.startswith("qty_total_drift") for w in rep["soft_warnings"])
    assert rep["hard_warnings"] == []


def test_reconcile_hard_blocks_on_no_rows():
    # Empty row set must be a hard block regardless of audit totals.
    from app.api import routes_dhl_clearance as rdc
    audit = {
        "rows": [],
        "invoice_totals": {"total_fob_usd": 100.0, "total_units": 5},
        "invoice_names": ["EJL-26-27-001"],
    }
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok_hard"] is False
    assert any("no_rows" in w for w in rep["hard_warnings"])


def test_reconcile_hard_blocks_on_negative_line_total():
    from app.api import routes_dhl_clearance as rdc
    audit = {
        "rows": [
            {"invoice_number": "EJL/26-27/001", "line_total": -50.0, "quantity": 2},
            {"invoice_number": "EJL/26-27/001", "line_total": 150.0, "quantity": 3},
        ],
        "invoice_totals": {"total_fob_usd": 100.0, "total_units": 5},
        "invoice_names": ["EJL-26-27-001"],
    }
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok_hard"] is False
    assert any("negative_line_total" in w for w in rep["hard_warnings"])


def test_reconcile_hard_blocks_on_zero_quantity():
    from app.api import routes_dhl_clearance as rdc
    audit = {
        "rows": [
            {"invoice_number": "EJL/26-27/001", "line_total": 100.0, "quantity": 0},
            {"invoice_number": "EJL/26-27/001", "line_total": 50.0, "quantity": 3},
        ],
        "invoice_totals": {"total_fob_usd": 150.0, "total_units": 3},
        "invoice_names": ["EJL-26-27-001"],
    }
    rep = rdc._reconcile_rows_with_audit_totals(audit)
    assert rep["ok_hard"] is False
    assert any("zero_or_negative_qty" in w for w in rep["hard_warnings"])


# ── 7. Empty source → no rows → guard fires at the route level ────────

def test_inject_no_op_when_no_db_rows_and_no_awb(fresh):
    from app.api import routes_dhl_clearance as rdc
    audit = {"batch_id": "SHIPMENT_EMPTY"}
    out = rdc._inject_rows_from_db_invoice_lines("SHIPMENT_EMPTY", audit)
    assert "rows" not in out or not out.get("rows")


# ── 8. Source-grep guards (no engine modification, no new wFirma/PZ/DHL)

def test_routes_dhl_does_not_modify_customs_description_engine():
    """PR-206 must NOT mutate the operator-managed engine module — only
    import its public callables.  We tolerate `from customs_description_engine
    import X` and reject any attribute assignment on the module object."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_dhl_clearance.py").read_text(encoding="utf-8")
    # The engine IS referenced — but only via `from customs_description_engine
    # import …` statements at the two production endpoint call sites.
    assert "from customs_description_engine import" in src, (
        "expected at least one `from customs_description_engine import …` "
        "import statement in routes_dhl_clearance.py"
    )
    # No monkey-patching: forbid `customs_description_engine.<name> =`
    # assignments anywhere in the file.
    import re as _re
    bad = [m for m in _re.finditer(
        r"customs_description_engine\.\w+\s*=",
        src,
    )]
    assert not bad, (
        f"PR-206 must not assign to customs_description_engine attributes; "
        f"hits: {[m.group(0) for m in bad]}"
    )


def test_pr206_adds_no_wfirma_pz_dhl_email_proforma_post_paths():
    """Diff guard via grep on the injection + reconciliation block."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_dhl_clearance.py").read_text(encoding="utf-8")
    s = src.index("def _inject_rows_from_db_invoice_lines(")
    e = src.index("def _find_sad_json(",  s)
    body = src[s:e]
    for bad in (
        "/api/v1/proforma/post",  "/api/v1/proforma/create",
        "/api/v1/pz/process",     "/api/v1/dhl/send",
        "wfirma_client.create_",  "send_email(",
    ):
        assert bad not in body, (
            f"PR-206 injection block must not invoke {bad!r}"
        )


def test_get_documents_by_awb_helper_exists():
    """document_db.py exposes a SELECT helper keyed on awb."""
    from app.services import document_db as ddb
    assert hasattr(ddb, "get_documents_by_awb")
    assert callable(getattr(ddb, "get_documents_by_awb"))


def test_inject_chain_uses_db_then_xlsx():
    """_inject_rows_from_sources must call DB first, then XLSX."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_dhl_clearance.py").read_text(encoding="utf-8")
    s = src.index("def _inject_rows_from_sources(")
    e = src.index("def _reconcile_rows_with_audit_totals(", s)
    body = src[s:e]
    i_db   = body.index("_inject_rows_from_db_invoice_lines(")
    i_xlsx = body.index("_inject_rows_from_xlsx(")
    assert i_db < i_xlsx, "DB injection must run before XLSX fallback"


def test_route_endpoint_uses_inject_from_sources_and_guards():
    """Both generate-description call sites must use the sources chain
    AND apply the lines-missing guard + reconciliation."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_dhl_clearance.py").read_text(encoding="utf-8")
    # _inject_rows_from_sources is wired in at the prod endpoints.
    assert src.count("audit = _inject_rows_from_sources(batch_id, audit)") >= 2
    # The lines-missing guard fires at the production endpoints.
    assert src.count('"lines_missing_for_description"') >= 2
    # And the reconciliation guard fires there too.
    assert src.count('"rows_audit_reconciliation_failed"') >= 2
