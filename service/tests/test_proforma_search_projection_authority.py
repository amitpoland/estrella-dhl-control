"""
Pro Forma search projection authority — AWB / Items / Total.

Invariant: search DTO fields are projections of existing authorities, never
a second calculator or a new permission surface.

  * Total  == detail Overview goods net = sum(qty × unit_price)
  * Items  == len(editable_lines) via _line_count (same as batch summary)
  * AWB    == outbound carrier tracking_ref when booked, else inbound via
              resolve_batch_tracking_no (never invents outbound from batch_id alone)
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import routes_proforma as rp
from app.services.tracking_service import resolve_batch_tracking_no


# ── Total authority ──────────────────────────────────────────────────────────


class TestDraftLinesTotalMatchesOverview:
    """_draft_lines_total must equal Overview sum(qty × unit_price)."""

    def test_zero_lines(self):
        assert rp._draft_lines_total("[]") == 0.0

    def test_one_line(self):
        blob = json.dumps([{"qty": 2, "unit_price": 10.5}])
        assert rp._draft_lines_total(blob) == 21.0

    def test_multiple_lines(self):
        blob = json.dumps([
            {"qty": 2, "unit_price": 10},
            {"qty": 3, "unit_price": 5.5},
            {"qty": 1, "unit_price": 100},
        ])
        # Overview: 20 + 16.5 + 100 = 136.5
        assert rp._draft_lines_total(blob) == 136.5

    def test_stale_line_value_ignored_uses_qty_times_price(self):
        """Detail Overview never reads line_value — search must match."""
        blob = json.dumps([
            {"qty": 2, "unit_price": 10, "line_value": 9999},  # stale
        ])
        assert rp._draft_lines_total(blob) == 20.0

    def test_missing_price_counts_as_zero_like_overview(self):
        blob = json.dumps([
            {"qty": 5, "unit_price": None},
            {"qty": 2, "unit_price": 7},
        ])
        assert rp._draft_lines_total(blob) == 14.0

    def test_malformed_json_returns_zero(self):
        assert rp._draft_lines_total("{not-json") == 0.0


class TestSearchResultTotalParity:
    """_draft_to_search_result.total == Overview formula on same lines."""

    def _draft(self, lines, **kw):
        return SimpleNamespace(
            id=1,
            batch_id=kw.get("batch_id", "SHIPMENT_7880850246_2026-08_c0b2ed5a"),
            client_name=kw.get("client_name", "Test Client"),
            client_contractor_id=kw.get("client_contractor_id", ""),
            draft_state="editing",
            status="editing",
            currency="EUR",
            wfirma_proforma_id=None,
            wfirma_proforma_fullnumber=None,
            editable_lines_json=json.dumps(lines),
            created_at="2026-08-01T00:00:00Z",
            updated_at="2026-08-01T00:00:00Z",
            sales_price_authority_total_eur=99999.0,  # must NOT override live total
        )

    def test_total_matches_overview_not_authority_snapshot(self):
        lines = [
            {"qty": 4, "unit_price": 12.25},
            {"qty": 1, "unit_price": 3},
        ]
        overview = round(4 * 12.25 + 1 * 3, 2)
        result = rp._draft_to_search_result(self._draft(lines), outbound_awb=None)
        assert result["total"] == overview
        assert result["total"] != 99999.0
        assert result["line_count"] == 2

    def test_empty_draft_total_zero_line_count_zero(self):
        result = rp._draft_to_search_result(self._draft([]), outbound_awb=None)
        assert result["total"] == 0.0
        assert result["line_count"] == 0


# ── Items authority ──────────────────────────────────────────────────────────


class TestLineCountNoDuplication:
    def test_line_count_is_len_editable_lines(self):
        blob = json.dumps([{"qty": 1}, {"qty": 2}, {"qty": 3}])
        assert rp._line_count(blob) == 3

    def test_line_count_zero(self):
        assert rp._line_count("[]") == 0

    def test_line_count_one(self):
        assert rp._line_count(json.dumps([{"qty": 1}])) == 1


# ── AWB authority ────────────────────────────────────────────────────────────


class TestSearchAwbAuthority:
    def test_outbound_preferred_over_inbound(self):
        d = SimpleNamespace(
            id=1,
            batch_id="SHIPMENT_7880850246_2026-08_c0b2ed5a",
            client_name="Client A",
            client_contractor_id="",
            draft_state="editing",
            status="editing",
            currency="EUR",
            wfirma_proforma_id=None,
            wfirma_proforma_fullnumber=None,
            editable_lines_json="[]",
            created_at="",
            updated_at="",
        )
        result = rp._draft_to_search_result(
            d, outbound_awb="9998887776", inbound_awb="7880850246",
        )
        assert result["awb"] == "9998887776"
        assert result["outbound_awb"] == "9998887776"
        assert result["inbound_awb"] == "7880850246"

    def test_inbound_fallback_uses_passed_resolved_awb(self):
        """Search projection consumes pre-resolved inbound — does not re-parse."""
        bid = "SHIPMENT_7880850246_2026-08_c0b2ed5a"
        d = SimpleNamespace(
            id=1,
            batch_id=bid,
            client_name="Client A",
            client_contractor_id="",
            draft_state="editing",
            status="editing",
            currency="EUR",
            wfirma_proforma_id=None,
            wfirma_proforma_fullnumber=None,
            editable_lines_json="[]",
            created_at="",
            updated_at="",
        )
        # Simulate bulk resolver output (audit.awb wins over batch embed)
        result = rp._draft_to_search_result(
            d, outbound_awb=None, inbound_awb="5555555555",
        )
        assert result["inbound_awb"] == "5555555555"
        assert result["awb"] == "5555555555"
        assert result["outbound_awb"] is None

    def test_bulk_inbound_prefers_audit_awb(self, tmp_path, monkeypatch):
        """audit.json awb is the stored inbound authority — not batch-id slice."""
        bid = "SHIPMENT_1111111111_2026-08_abcd"
        out_dir = tmp_path / "outputs" / bid
        out_dir.mkdir(parents=True)
        (out_dir / "audit.json").write_text(
            json.dumps({"awb": "9999999999", "tracking_no": "9999999999"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(rp.settings, "storage_root", tmp_path)
        m = rp._bulk_inbound_awbs_for_batches([bid])
        assert m[bid] == "9999999999"
        # Must NOT silently prefer the embedded 1111111111 when audit exists
        assert m[bid] != "1111111111"

    def test_bulk_inbound_falls_back_to_canonical_resolver(self, tmp_path, monkeypatch):
        """No audit → resolve_batch_tracking_no's existing SHIPMENT_ fallback."""
        bid = "SHIPMENT_7880850246_2026-08_c0b2ed5a"
        monkeypatch.setattr(rp.settings, "storage_root", tmp_path)
        m = rp._bulk_inbound_awbs_for_batches([bid])
        assert m[bid] == resolve_batch_tracking_no({}, bid)

    def test_bulk_outbound_exact_client_match(self, tmp_path, monkeypatch):
        from app.services.carrier.persistence import shipment_db as csdb

        db = tmp_path / "carrier_shipments.db"
        csdb.init_db(db)
        # Insert two outbound rows for same batch, different clients
        with csdb._connect(db) as conn:
            for key, client, awb in [
                ("k1", "Client A", "1111111111"),
                ("k2", "Client B", "2222222222"),
            ]:
                conn.execute(
                    "INSERT INTO carrier_shipments "
                    "(idempotency_key, batch_id, mode, state, simulated, "
                    " client_ref, tracking_ref) "
                    "VALUES (?, ?, 'live', 'complete', 0, ?, ?)",
                    (key, "BATCH_X", client, awb),
                )
            conn.commit()

        monkeypatch.setattr(rp, "_carrier_shipment_db_path", lambda: db)
        drafts = [
            SimpleNamespace(batch_id="BATCH_X", client_name="Client A"),
            SimpleNamespace(batch_id="BATCH_X", client_name="Client B"),
            SimpleNamespace(batch_id="BATCH_X", client_name="Client C"),  # no row
        ]
        m = rp._bulk_outbound_awbs_for_drafts(drafts)
        assert m[("BATCH_X", "Client A")] == "1111111111"
        assert m[("BATCH_X", "Client B")] == "2222222222"
        assert m[("BATCH_X", "Client C")] is None

    def test_bulk_outbound_no_cross_client_leak_on_single_scoped_row(
        self, tmp_path, monkeypatch
    ):
        """A single row scoped to Client A must NOT leak to Client B."""
        from app.services.carrier.persistence import shipment_db as csdb

        db = tmp_path / "carrier_shipments.db"
        csdb.init_db(db)
        with csdb._connect(db) as conn:
            conn.execute(
                "INSERT INTO carrier_shipments "
                "(idempotency_key, batch_id, mode, state, simulated, "
                " client_ref, tracking_ref) "
                "VALUES ('k1', 'BATCH_Y', 'live', 'complete', 0, 'Client A', '3333333333')"
            )
            conn.commit()

        monkeypatch.setattr(rp, "_carrier_shipment_db_path", lambda: db)
        drafts = [
            SimpleNamespace(batch_id="BATCH_Y", client_name="Client B"),
        ]
        m = rp._bulk_outbound_awbs_for_drafts(drafts)
        assert m[("BATCH_Y", "Client B")] is None


# ── Permission alias (source pin) ────────────────────────────────────────────


def test_proforma_search_alias_is_proforma_not_new_permission():
    from app.auth.permissions import PAGE_ALIASES, page_is_allowed, permissions_for_role
    from app.auth.permissions import allowed_pages_for_permissions

    assert PAGE_ALIASES["proforma_search"] == "proforma"
    admin = allowed_pages_for_permissions(permissions_for_role("admin"))
    assert page_is_allowed("proforma_search", admin) == page_is_allowed("proforma", admin)
    # master_viewer has no proforma → search also denied
    mv = allowed_pages_for_permissions(permissions_for_role("master_viewer"))
    assert not page_is_allowed("proforma", mv)
    assert not page_is_allowed("proforma_search", mv)
