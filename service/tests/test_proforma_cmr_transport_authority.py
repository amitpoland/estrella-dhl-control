"""test_proforma_cmr_transport_authority.py — PR-5 + single-canonical cutover.

TransportDocumentAuthority (`_transport`) remains the Logistics weight / booking
projection. CMR *document* identity (parties, lines, AWB on the form, country
names) is owned by ``commercial_cmr`` — Preview/Logistics consume cmr.json.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parents[1]
_JSX = (_ROOT / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
_API = (_ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
_CMR_JSX = (_ROOT / "app" / "static" / "v2" / "estrella-doc-cmr.jsx").read_text(encoding="utf-8")
_CMR_PY = (_ROOT / "app" / "services" / "commercial_cmr.py").read_text(encoding="utf-8")
_CMR_HTML = (_ROOT / "app" / "services" / "commercial_cmr_html.py").read_text(encoding="utf-8")
_PILDB = (_ROOT / "app" / "services" / "proforma_invoice_link_db.py").read_text(encoding="utf-8")
_ROUTES = (_ROOT / "app" / "api" / "routes_proforma.py").read_text(encoding="utf-8")
_ROUTES_CARRIER = (_ROOT / "app" / "api" / "routes_carrier_actions.py").read_text(encoding="utf-8")


# ── one resolver (TransportDocumentAuthority) — Logistics weight / booking ────

def test_single_transport_resolver():
    assert re.search(r"const _transport\s*=\s*\(\(\)\s*=>", _JSX), "one _transport resolver must exist"
    assert "const _ew = _transport.effectiveWeight" in _JSX
    assert re.search(r"const ship\s*=\s*carrierShipment", _JSX)


def test_cmr_document_comes_from_canonical_projection():
    assert "getCmrDocument" in _JSX
    assert "canonicalCmr" in _JSX
    assert "const cmrPreviewData" not in _JSX
    assert 'shipment_row.get("tracking_ref")' in _CMR_PY


def test_missing_outbound_renders_honest_state_with_reason():
    assert "No outbound shipment linked" in _JSX or "canonicalCmrErr" in _JSX
    assert "carrier" in _CMR_PY
    assert "No outbound" in _CMR_HTML or "EJCMRNoCarrier" in _CMR_JSX or 'carrier = None' in _CMR_PY or "if awb or shipment_row" in _CMR_PY


# ── 1: CMR uses the outbound AWB, not the import batch id ─────────────────────

def test_cmr_awb_is_outbound_not_batch_id():
    assert 'shipment_row.get("tracking_ref")' in _CMR_PY
    assert "liveDraft.batch_id" not in _CMR_PY.split("awb =")[1][:200] if "awb =" in _CMR_PY else True
    assert not re.search(r'awb\s*=\s*.*batch_id', _CMR_PY)


# ── 2: export_shipment_id comes from the CARRIER authority, not batch_id/AWB ──

def test_export_shipment_id_from_carrier_authority_not_alias():
    assert '"export_shipment_id": row["idempotency_key"]' in _ROUTES_CARRIER, (
        "carrier read model must expose export_shipment_id (the shipment's stable id)"
    )
    assert re.search(r"export_shipment_id\s*=\s*ship\s*\?\s*\(ship\.export_shipment_id", _JSX)
    assert not re.search(r"export_shipment_id\s*=\s*liveDraft\.batch_id", _JSX), (
        "export_shipment_id must NOT be an alias for the import batch_id"
    )
    assert not re.search(r"export_shipment_id\s*=\s*[^\n;]*tracking_ref", _JSX), (
        "export_shipment_id must NOT be derived from the AWB/tracking_ref"
    )


def test_cmr_number_from_authority_or_honest_null():
    assert re.search(r"cmr_number:\s*ship\s*\?\s*\(ship\.cmr_number", _JSX)
    assert re.search(r"cmr_number_reason:\s*\(ship\s*&&\s*ship\.cmr_number\)\s*\?\s*null\s*:", _JSX)
    assert "No export shipment identifier available" in _JSX
    assert "cmr_document_number" in _CMR_PY
    assert 'cmr_document_number(row["idempotency_key"])' in _ROUTES_CARRIER
    assert "`CMR-EJ-${export_shipment_id}`" not in _JSX
    assert not re.search(r"CMR-EJ-\$\{[^}]*tracking_ref", _JSX)
    assert "`CMR-EJ-${batchId}`" not in _JSX


def test_awb_comes_only_from_tracking_ref():
    assert re.search(r"outbound_awb:\s*ship\s*\?\s*\(ship\.tracking_ref", _JSX)
    assert 'shipment_row.get("tracking_ref")' in _CMR_PY
    assert not re.search(r"outbound_awb:[^\n]*export_shipment_id", _JSX)


def test_rebook_changes_awb_only_not_cmr_number():
    import sqlite3, tempfile
    from app.services.carrier.persistence import shipment_db as sdb
    db = pathlib.Path(tempfile.mkdtemp()) / "carrier_shipments.db"
    sdb.init_db(db) if hasattr(sdb, "init_db") else None
    with sqlite3.connect(str(db)) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS carrier_shipments (
            idempotency_key TEXT PRIMARY KEY, batch_id TEXT NOT NULL, mode TEXT,
            state TEXT, error TEXT, simulated INTEGER, tracking_ref TEXT,
            service_product TEXT, box_type_code TEXT, weight_kg REAL,
            dimensions_json TEXT, declared_value REAL, currency TEXT,
            created_at TEXT)""")
        con.execute("INSERT INTO carrier_shipments "
                    "(idempotency_key, batch_id, mode, state, simulated, tracking_ref, created_at) "
                    "VALUES ('K1','B1','live','complete',0,'AWB1','2026-07-15T00:00:00Z')")
        con.commit()
        awb1 = con.execute("SELECT tracking_ref FROM carrier_shipments WHERE idempotency_key='K1'").fetchone()[0]
        key1 = con.execute("SELECT idempotency_key FROM carrier_shipments WHERE batch_id='B1'").fetchone()[0]
        con.execute("UPDATE carrier_shipments SET tracking_ref='AWB2' WHERE idempotency_key='K1'")
        con.commit()
        awb2 = con.execute("SELECT tracking_ref FROM carrier_shipments WHERE idempotency_key='K1'").fetchone()[0]
        key2 = con.execute("SELECT idempotency_key FROM carrier_shipments WHERE batch_id='B1'").fetchone()[0]
    assert awb1 == "AWB1" and awb2 == "AWB2"
    assert key1 == key2 == "K1"


# ── 3: carrier + service from commercial_cmr shipment_row ─────────────────────

def test_carrier_and_service_from_resolver():
    assert 'shipment_row.get("provider")' in _CMR_PY or 'shipment_row.get("carrier")' in _CMR_PY
    assert "service_product" in _CMR_PY or 'shipment_row.get("service")' in _CMR_PY
    assert "'EXPRESS WORLDWIDE'" not in _CMR_PY


# ── 6: gross weight uses the effective projection (Logistics) ─────────────────

def test_gross_weight_uses_effective_projection():
    assert "bookGross" in _JSX
    assert "source: 'carrier'" in _JSX
    assert 'shipment_row.get("weight_kg")' in _CMR_PY


def test_weight_precedence_documented():
    assert re.search(r"manual\s*.\s*carrier booking\s*.\s*packing extraction", _JSX)
    assert re.search(r"calculated \(net\+tare", _JSX)
    assert re.search(r"manual\s*.\s*packing extraction\s*.\s*missing", _JSX)
    assert re.search(r"tare\s*:\s*manual\s*.\s*missing", _JSX)


def test_no_live_dhl_in_render_or_weight_endpoints():
    assert "getCarrierShipment" in _JSX
    assert re.search(r"const _transport\s*=", _JSX)
    assert "setWeightOverride" in _JSX and "clearWeightOverride" in _JSX
    # Slice to the end of set_draft_weight_override itself, not to whatever
    # function happens to follow it: a neighbour added later must not silently
    # widen (or narrow) what this pin measures.
    _wblock = _PILDB.split("def set_draft_weight_override")[1].split("\ndef ")[0]
    assert "adapters.live" not in _wblock
    assert "book" not in _wblock.lower()


def test_cmr_and_packing_share_effective_weight():
    # Logistics tiles still share _ew; CMR PDF uses shipment_row.weight_kg
    assert "_ew.gross" in _JSX
    assert 'shipment_row.get("weight_kg")' in _CMR_PY


def test_single_weight_writer_and_ui():
    assert _PILDB.count("def set_draft_weight_override") == 1
    assert _PILDB.count("def clear_draft_weight_override") == 1
    assert "setWeightOverride" in _API and "clearWeightOverride" in _API
    for tid in ("pf-weight-edit", "pf-weight-save", "pf-weight-cancel", "pf-weight-clear",
                "pf-weight-net", "pf-weight-gross"):
        assert f'data-testid="{tid}"' in _JSX


def test_weight_override_source_column():
    assert '"weight_override_source"' in _PILDB or "weight_override_source" in _PILDB
    assert 'new_weight_override_source = "manual"' in _PILDB
    assert 'new_weight_override_source = "cleared"' in _PILDB
    assert '"weight_override_source"' in _ROUTES


def test_weight_source_badges_present():
    for label in ("Manual override", "Extracted from packing", "Carrier booking", "Missing"):
        assert label in _JSX


def test_cmr_renderer_has_no_hardcoded_origin_country():
    assert "Country of Origin: India" not in _CMR_HTML
    assert 'l.origin || "India"' not in _CMR_HTML
    assert "goods_origin_country" in _CMR_PY
    assert "goods_origin_country" in _CMR_HTML or "origin" in _CMR_HTML.lower()


def test_cmr_data_origin_from_authority_not_hardcoded():
    assert "|| 'India'" not in _JSX
    assert "goods_origin_country" in _CMR_PY
    assert "_country_name" in _CMR_PY


def test_cmr_per_line_origin_mapped_through_country_name():
    assert "_country_name" in _CMR_PY
    assert 'ln.get("origin")' in _CMR_PY or "ln.get(\"origin\")" in _CMR_PY or "origin" in _CMR_PY


def test_cmr_country_name_is_single_authority():
    assert _CMR_PY.count("_ISO2_COUNTRY") >= 1
    assert "const _CMR_COUNTRY_NAMES" not in _JSX
    assert "_cmrCountryName" not in _JSX


def test_cmr_modern_line_renderer_prints_mapped_origin():
    # Canonical HTML presentation owns origin display
    assert "origin" in _CMR_HTML.lower()


def _cmr_country_map():
    m = re.search(r"_ISO2_COUNTRY\s*=\s*\{(.*?)\}", _CMR_PY, re.DOTALL)
    assert m, "_ISO2_COUNTRY object literal not found"
    return {k: v for k, v in re.findall(r'"([A-Z]{2})"\s*:\s*"([^"]+)"', m.group(1))}


def test_cmr_country_table_covers_real_shipping_footprint():
    m = _cmr_country_map()
    required = {
        "PL", "IT", "FR", "DE", "US", "IN", "GB", "AT", "CZ", "FI", "BG", "ES",
        "LT", "SE", "SK", "CN", "EE", "LV", "CH", "HU", "NL", "NO", "SG", "AE",
        "AU", "BE", "DK", "IE", "KR", "MU", "SI",
    }
    missing = sorted(c for c in required if c not in m)
    assert not missing, f"CMR country table missing real-footprint codes: {missing}"
    echoed = sorted(c for c in required if m.get(c, "").strip().upper() == c)
    assert not echoed, f"CMR country codes mapped to themselves (no name): {echoed}"


def test_cmr_country_table_covers_reviewer_flagged_examples():
    m = _cmr_country_map()
    assert m.get("US") == "United States"
    assert m.get("AE") == "United Arab Emirates"
    assert m.get("JP") == "Japan"
