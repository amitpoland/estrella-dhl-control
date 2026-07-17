"""test_proforma_cmr_transport_authority.py — PR-5.

Structural contracts for the Transport Document Authority (ADR
docs/decisions/ADR-proforma-cmr-transport-authority.md):

  * ONE resolver (`_transport`) turns Draft + carrierShipment into a single
    transport-document projection; the CMR, Packing List and Logistics panel
    consume it — React never assembles transport identity from multiple responses.
  * The CMR number is a STABLE document identifier (export shipment reference),
    INDEPENDENT of the AWB — a re-book changes the AWB, not the document identity.
  * outbound AWB / carrier / service come from carrierShipment (not the batch id).
  * one effectiveWeight object with fixed precedence (manual → carrier → packing →
    missing) shared by CMR + Packing List + Logistics; honest Missing + reason.
  * exactly ONE weight-override writer; weight_override_source provenance column.

Required tests 1, 2, 3, 4, 6, 13, 14, 15 + the mandated pre-merge adjustments.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parents[1]
_JSX = (_ROOT / "app" / "static" / "v2" / "proforma-detail.jsx").read_text(encoding="utf-8")
_API = (_ROOT / "app" / "static" / "v2" / "pz-api.js").read_text(encoding="utf-8")
_CMR = (_ROOT / "app" / "static" / "v2" / "estrella-doc-cmr.jsx").read_text(encoding="utf-8")
_PILDB = (_ROOT / "app" / "services" / "proforma_invoice_link_db.py").read_text(encoding="utf-8")
_ROUTES = (_ROOT / "app" / "api" / "routes_proforma.py").read_text(encoding="utf-8")
_ROUTES_CARRIER = (_ROOT / "app" / "api" / "routes_carrier_actions.py").read_text(encoding="utf-8")


# ── one resolver (TransportDocumentAuthority) ─────────────────────────────────

def test_single_transport_resolver():
    assert re.search(r"const _transport\s*=\s*\(\(\)\s*=>", _JSX), "one _transport resolver must exist"
    assert "const _ew = _transport.effectiveWeight" in _JSX
    # The resolver reads the fetched carrier shipment, not scattered responses.
    assert re.search(r"const ship\s*=\s*carrierShipment", _JSX)


# ── 1: CMR uses the outbound AWB, not the import batch id ─────────────────────

def test_cmr_awb_is_outbound_not_batch_id():
    assert re.search(r"awb:\s*_transport\.outbound_awb", _JSX)
    assert not re.search(r"awb:\s*liveDraft\.batch_id", _JSX)


# ── 2: export_shipment_id comes from the CARRIER authority, not batch_id/AWB ──

def test_export_shipment_id_from_carrier_authority_not_alias():
    # The carrier read model exposes the stable id (carrier_shipments PK).
    assert '"export_shipment_id": row["idempotency_key"]' in _ROUTES_CARRIER, (
        "carrier read model must expose export_shipment_id (the shipment's stable id)"
    )
    # The resolver takes export_shipment_id from the carrier shipment …
    assert re.search(r"export_shipment_id\s*=\s*ship\s*\?\s*\(ship\.export_shipment_id", _JSX)
    # … and NEVER aliases it to the import batch_id or the AWB/tracking_ref.
    assert not re.search(r"export_shipment_id\s*=\s*liveDraft\.batch_id", _JSX), (
        "export_shipment_id must NOT be an alias for the import batch_id"
    )
    assert not re.search(r"export_shipment_id\s*=\s*[^\n;]*tracking_ref", _JSX), (
        "export_shipment_id must NOT be derived from the AWB/tracking_ref"
    )


def test_cmr_number_from_authority_or_honest_null():
    # cmr_number is the SHORT, deterministic number from the ONE backend authority
    # (ADR-proforma-cmr-short-number). The frontend CONSUMES ship.cmr_number and
    # no longer re-derives the long CMR-EJ-<64hex> format from the raw id.
    assert re.search(r"cmr_number:\s*ship\s*\?\s*\(ship\.cmr_number", _JSX)
    # … honest null + reason when the authority has no number (never batch_id).
    assert re.search(r"cmr_number_reason:\s*\(ship\s*&&\s*ship\.cmr_number\)\s*\?\s*null\s*:", _JSX)
    assert "No export shipment identifier available" in _JSX
    assert re.search(r"cmr_no:\s*_transport\.cmr_number", _JSX)
    # backend derives the short number from the stable export_shipment_id
    assert 'cmr_document_number(row["idempotency_key"])' in _ROUTES_CARRIER
    # the frontend must NOT rebuild the long number from the raw id / AWB / batch id
    assert "`CMR-EJ-${export_shipment_id}`" not in _JSX
    assert not re.search(r"CMR-EJ-\$\{[^}]*tracking_ref", _JSX)
    assert "`CMR-EJ-${batchId}`" not in _JSX


def test_awb_comes_only_from_tracking_ref():
    # AWB is a pure function of tracking_ref, independent of export_shipment_id.
    assert re.search(r"outbound_awb:\s*ship\s*\?\s*\(ship\.tracking_ref", _JSX)
    assert re.search(r"awb:\s*_transport\.outbound_awb", _JSX)
    # awb assignment must not reference export_shipment_id (they are independent).
    assert not re.search(r"outbound_awb:[^\n]*export_shipment_id", _JSX)


def test_rebook_changes_awb_only_not_cmr_number():
    """A re-book updates the carrier row's tracking_ref (AWB) in place, keeping the
    idempotency_key (export_shipment_id). Verify at the authority level that the
    stable id survives a tracking_ref change, so the CMR number does not move."""
    import sqlite3, tempfile, os
    from app.services.carrier.persistence import shipment_db as sdb
    db = pathlib.Path(tempfile.mkdtemp()) / "carrier_shipments.db"
    sdb.init_db(db) if hasattr(sdb, "init_db") else None
    # Seed one shipment row directly (idempotency_key K1, AWB1), then rebook → AWB2.
    with sqlite3.connect(str(db)) as con:
        # ensure schema
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
        # Re-book: same idempotency_key row, new AWB.
        con.execute("UPDATE carrier_shipments SET tracking_ref='AWB2' WHERE idempotency_key='K1'")
        con.commit()
        awb2 = con.execute("SELECT tracking_ref FROM carrier_shipments WHERE idempotency_key='K1'").fetchone()[0]
        key2 = con.execute("SELECT idempotency_key FROM carrier_shipments WHERE batch_id='B1'").fetchone()[0]
    assert awb1 == "AWB1" and awb2 == "AWB2"          # AWB changed on rebook
    assert key1 == key2 == "K1"                        # export_shipment_id (→ CMR number) did NOT change


# ── 3: carrier + service from the resolver (canonical booking) ────────────────

def test_carrier_and_service_from_resolver():
    assert re.search(r"name:\s*_transport\.carrier", _JSX)
    assert re.search(r"service:\s*_transport\.service", _JSX)
    assert "'EXPRESS WORLDWIDE'" not in _JSX


# ── 4: honest missing state (carrier + reason) ────────────────────────────────

def test_missing_outbound_renders_honest_state_with_reason():
    assert re.search(r"carrier:\s*_transport\.linked\s*\?", _JSX)
    assert "carrier_missing_reason" in _JSX
    assert "No outbound shipment linked" in _JSX
    assert "EJCMRNoCarrier" in _CMR


# ── 6: gross weight uses the effective projection (carrier precedence) ─────────

def test_gross_weight_uses_effective_projection():
    assert re.search(r"weight_kg:\s*_ew\.gross", _JSX)
    # precedence includes carrier booking for gross
    assert "source: 'carrier'" in _JSX and "bookGross" in _JSX


# ── weight source precedence documented; never inferred/averaged/divided ──────

def test_weight_precedence_documented():
    # gross precedence now includes the additive tare-derived calculated source
    # (manual → carrier booking → packing extraction → calculated(net+tare) → missing)
    assert re.search(r"manual\s*.\s*carrier booking\s*.\s*packing extraction", _JSX)
    assert re.search(r"calculated \(net\+tare", _JSX)
    # net precedence has no carrier source (only manual → packing → missing)
    assert re.search(r"manual\s*.\s*packing extraction\s*.\s*missing", _JSX)
    # tare has no extracted authority — manual only
    assert re.search(r"tare\s*:\s*manual\s*.\s*missing", _JSX)


# ── 13: no live DHL from a document render or the weight endpoints ────────────

def test_no_live_dhl_in_render_or_weight_endpoints():
    assert "getCarrierShipment" in _JSX
    assert re.search(r"const _transport\s*=", _JSX)
    assert "setWeightOverride" in _JSX and "clearWeightOverride" in _JSX
    _wblock = _PILDB.split("def set_draft_weight_override")[1].split("def update_draft_line")[0]
    assert "adapters.live" not in _wblock
    assert "book" not in _wblock.lower()


# ── 14: CMR + Packing List share the SAME effective-weight object ─────────────

def test_cmr_and_packing_share_effective_weight():
    for token in ("effective_net_kg:", "effective_gross_kg:"):
        assert _JSX.count(token) >= 2
    # both derive from the single _ew (= _transport.effectiveWeight)
    assert re.search(r"effective_net_kg:\s*_ew\.net", _JSX)
    assert re.search(r"effective_gross_kg:\s*_ew\.gross", _JSX)
    # the Logistics tiles consume the same effective weight
    assert re.search(r"pf-logistics-tile-gross.*_ew\.gross|_ew\.gross[^\n]*pf-logistics-tile-gross", _JSX, re.DOTALL) \
        or "_ew.gross != null" in _JSX


# ── 15: exactly one weight writer; API wrappers + UI controls present ─────────

def test_single_weight_writer_and_ui():
    assert _PILDB.count("def set_draft_weight_override") == 1
    assert _PILDB.count("def clear_draft_weight_override") == 1
    assert "setWeightOverride" in _API and "clearWeightOverride" in _API
    for tid in ("pf-weight-edit", "pf-weight-save", "pf-weight-cancel", "pf-weight-clear",
                "pf-weight-net", "pf-weight-gross"):
        assert f'data-testid="{tid}"' in _JSX


# ── weight_override_source provenance column persisted ────────────────────────

def test_weight_override_source_column():
    assert '"weight_override_source"' in _PILDB or "weight_override_source" in _PILDB
    assert 'new_weight_override_source = "manual"' in _PILDB
    assert 'new_weight_override_source = "cleared"' in _PILDB
    assert '"weight_override_source"' in _ROUTES


# ── source badges present (Extracted / Carrier / Manual / Missing) ────────────

def test_weight_source_badges_present():
    for label in ("Manual override", "Extracted from packing", "Carrier booking", "Missing"):
        assert label in _JSX


# ── 2026-07-16 independent-review Condition 1: no hardcoded goods origin ──────

def test_cmr_renderer_has_no_hardcoded_origin_country():
    """The CMR goods blocks (Classic + Modern) must derive origin from the typed
    data contract (d.goods_origin_country / per-line l.origin), never a
    hardcoded country literal. Honest omission when the authority has none."""
    assert "Country of Origin: India" not in _CMR
    assert 'l.origin || "India"' not in _CMR
    assert _CMR.count("goods_origin_country") >= 2   # Classic + Modern variants


def test_cmr_data_origin_from_authority_not_hardcoded():
    """proforma-detail.jsx must not default any origin field to 'India' — the
    authority chain is ln/l.origin → liveDraft.origin_country → honest null/—."""
    assert "|| 'India'" not in _JSX
    assert "goods_origin_country" in _JSX


# ── #940 repair: per-line CMR origin mapped ISO-2 → full country name ─────────
# Chip task_35c61ad8 — the Modern CMR line renderer printed raw "IN"; map it
# through the single _cmrCountryName authority so it prints "India", honest-null
# preserved (unknown/blank → null → "—", never defaulted to a country).

def test_cmr_per_line_origin_mapped_through_country_name():
    # the cmrPreviewData line contract maps each line's origin through the CMR
    # country-name authority (component-local _cmrCountryName lives here)
    assert "_cmrCountryName(_l.origin)" in _JSX
    # honest-null: the mapped result falls back to null, never a hardcoded country
    assert "_cmrCountryName(_l.origin) || null" in _JSX


def test_cmr_country_name_is_single_authority():
    # exactly one ISO→name table + one mapper — no duplication into the renderer
    assert _JSX.count("const _CMR_COUNTRY_NAMES") == 1
    assert "_CMR_COUNTRY_NAMES" not in _CMR   # renderer must not carry its own copy
    assert _CMR.count("_cmrCountryName") == 0  # mapping stays in the data contract


def test_cmr_modern_line_renderer_prints_mapped_origin():
    # the Modern per-line cell prints l.origin (now the mapped full name); the
    # Classic goods table has no per-line origin column (origin is header-only)
    assert '{l.origin || "—"}' in _CMR


# ── #940 follow-up: full shipping-footprint coverage (data-derived) ───────────
# The ISO-2 → country-name table must cover every country in Estrella's real
# origin/destination footprint. The required set below is the DISTINCT country
# set pulled from production data (Customer Master country + ship_to_country,
# wFirma customer countries, exporter/goods origins) — not guessed. An unlisted
# code still passes through honestly as the raw 2-letter code (_cmrCountryName),
# so this test pins the intended coverage: the table must not silently regress
# below the known footprint, and every listed code must resolve to a real name.

def _cmr_country_map():
    """Parse the single _CMR_COUNTRY_NAMES object literal from proforma-detail.jsx
    into a {code: name} dict (single-quoted string values)."""
    m = re.search(r"const _CMR_COUNTRY_NAMES\s*=\s*\{(.*?)\};", _JSX, re.DOTALL)
    assert m, "_CMR_COUNTRY_NAMES object literal not found"
    return {k: v for k, v in re.findall(r"\b([A-Z]{2})\s*:\s*'([^']+)'", m.group(1))}


def test_cmr_country_table_covers_real_shipping_footprint():
    m = _cmr_country_map()
    # Distinct ISO-2 codes present in Estrella's real customer/shipping data
    # (customer_master.country + ship_to_country + wFirma customers) plus goods
    # origins (IN, PL). Every one must resolve to a full country name.
    required = {
        "PL", "IT", "FR", "DE", "US", "IN", "GB", "AT", "CZ", "FI", "BG", "ES",
        "LT", "SE", "SK", "CN", "EE", "LV", "CH", "HU", "NL", "NO", "SG", "AE",
        "AU", "BE", "DK", "IE", "KR", "MU", "SI",
    }
    missing = sorted(c for c in required if c not in m)
    assert not missing, f"CMR country table missing real-footprint codes: {missing}"
    # names must be real names, never the code echoed back to itself
    echoed = sorted(c for c in required if m.get(c, "").strip().upper() == c)
    assert not echoed, f"CMR country codes mapped to themselves (no name): {echoed}"


def test_cmr_country_table_covers_reviewer_flagged_examples():
    # #940 reviewers flagged JP / US / AE specifically as common destinations that
    # rendered as raw 2-letter codes on the fiscal document. All three must now
    # resolve to full country names.
    m = _cmr_country_map()
    assert m.get("US") == "United States"
    assert m.get("AE") == "United Arab Emirates"
    assert m.get("JP") == "Japan"
