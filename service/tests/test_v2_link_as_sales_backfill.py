"""
test_v2_link_as_sales_backfill.py — V2 link-as-sales backfill action with a
Customer Master contractor picker.

PR #696 made POST /packing/{batch}/link-as-sales accept and persist
client_contractor_id, but no V2 surface sent it. This adds the V2-only backfill
action on the proforma (sales) list page. V1 stays frozen (Lesson F). These
static-contract tests pin the authority rules and the layer discipline:

  1. The operator-selected Customer Master contractor_id is sent as the customer
     authority (client_contractor_id) — rules 1-2.
  2. client_name is display-only once a contractor is selected; the free-text
     name input exists only in the no-contractor fallback path — rule 3.
  3. No contractor selected → clearly-labelled name-fallback — rule 4.
  4. contractor_id is read ONLY from the picked Customer Master record, never
     inferred from text — rule 5.
  5. No V1 frozen page is wired to this component.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
_BACKFILL = _V2 / "link-as-sales-backfill.jsx"
_PZAPI = _V2 / "pz-api.js"
_LIST = _V2 / "proforma-list.jsx"
_INDEX = _V2 / "index.html"


@pytest.fixture(scope="module")
def backfill_src():
    return _BACKFILL.read_text(encoding="utf-8")


# ── pz-api transport ─────────────────────────────────────────────────────────

def test_pzapi_has_link_as_sales_and_packing_documents():
    src = _PZAPI.read_text(encoding="utf-8")
    assert "linkAsSales:" in src
    assert "getPackingDocuments:" in src
    # link-as-sales posts client_mappings (the backend contract)
    assert "client_mappings" in src
    # transport-only: uses the mutation helper, no business logic
    assert "/packing/" in src and "/link-as-sales" in src
    assert "/packing-documents" in src


# ── rule 1-2: contractor_id is sent as the customer authority ────────────────

def test_sends_client_contractor_id_in_mappings(backfill_src):
    assert "client_contractor_id" in backfill_src
    # the cid comes from the picked Customer Master record's contractor id ONLY
    assert "cm.bill_to_contractor_id" in backfill_src
    # it is submitted via the link-as-sales transport
    assert "PzApi.linkAsSales" in backfill_src


def test_contractor_id_only_from_picked_record_never_from_text(backfill_src):
    """rule 5: contractor_id is read from the selected CM record, never inferred
    from the parsed/free-text name."""
    # the mapping cid is gated on a picked record (cm), blank otherwise
    assert 'client_contractor_id: cm ? String(cm.bill_to_contractor_id' in backfill_src
    # the free-text name must never feed a contractor id
    assert "client_contractor_id: names" not in backfill_src
    assert "client_contractor_id: d.suggested_client_name" not in backfill_src


# ── rule 3: client_name display-only once a contractor is selected ───────────

def test_client_name_display_only_after_selection(backfill_src):
    # when a contractor is picked, the sent name is the contractor's name
    assert "cm ? (cm.bill_to_name" in backfill_src
    # the editable free-text name input renders ONLY in the no-contractor path
    assert "las-fallback-name-" in backfill_src
    idx = backfill_src.index("las-fallback-name-")
    # the fallback name input is inside the `{!cm && (` no-contractor branch
    guard_region = backfill_src[max(0, idx - 800):idx]
    assert "{!cm && (" in guard_region
    # and a display-only note appears when a contractor IS selected
    assert "display-only once a contractor is selected" in backfill_src


# ── rule 4: name-fallback clearly labelled ───────────────────────────────────

def test_name_fallback_clearly_labelled(backfill_src):
    assert "Name-fallback" in backfill_src
    assert "las-fallback-warn-" in backfill_src
    # an explicit banner warns the operator about name-fallback mode
    assert "name-fallback" in backfill_src.lower()
    assert "las-fallback-banner" in backfill_src
    assert "parsed/free-text name fallback" in backfill_src


# ── uses the Customer Master search (picker) ─────────────────────────────────

def test_uses_customer_master_search(backfill_src):
    assert "PzApi.listCustomerMaster" in backfill_src
    assert "las-cm-picker-" in backfill_src
    # shows contractor name + VAT/country on selection (authority transparency)
    assert "bill_to_name" in backfill_src
    assert "Customer Master authority" in backfill_src


# ── result displays the authority source ─────────────────────────────────────

def test_result_displays_authority_source(backfill_src):
    assert "las-result" in backfill_src
    # per-row authority: contractor id vs name-fallback
    assert "r.client_contractor_id ? `contractor" in backfill_src
    assert "name-fallback" in backfill_src
    assert "sales line(s)" in backfill_src


# ── layer discipline: transport only, explicit write, operator-driven ────────

def test_no_auto_fetch_on_mount_and_explicit_write(backfill_src):
    # operator opens the panel — no fetch at mount (no useEffect auto-load)
    assert "useEffect" not in backfill_src
    assert "btn-open-link-as-sales-backfill" in backfill_src
    # explicit submit button labelled with what it does
    assert "btn-link-as-sales-submit" in backfill_src
    assert "to sales`" in backfill_src
    # no forbidden write surfaces (no wFirma/PZ/invoice creation from this UI)
    for forbidden in ("wfirma_create", "create-pz", "to-invoice", "/post`"):
        assert forbidden not in backfill_src


def test_testids_present_on_controls(backfill_src):
    for tid in ("link-as-sales-backfill", "btn-open-link-as-sales-backfill",
                "btn-link-as-sales-submit", "btn-close-link-as-sales-backfill"):
        assert f'data-testid="{tid}"' in backfill_src or f"data-testid={{`{tid}" in backfill_src \
            or tid in backfill_src


# ── wiring: rendered on the proforma list page; registered in index.html ─────

def test_rendered_on_proforma_list_page():
    src = _LIST.read_text(encoding="utf-8")
    assert "LinkAsSalesBackfill" in src
    assert "batchId={batchId}" in src
    assert "onLinked=" in src


def test_registered_in_index_html():
    src = _INDEX.read_text(encoding="utf-8")
    assert "link-as-sales-backfill.jsx" in src


# ── Lesson F: V1 frozen pages are NOT wired to this component ─────────────────

def test_v1_pages_not_touched():
    for v1 in ("dashboard.html", "shipment-detail.html"):
        p = _V2.parent / v1
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            assert "LinkAsSalesBackfill" not in txt
            assert "link-as-sales-backfill" not in txt
    # the V2 component itself must not reach into a V1 page
    src = _BACKFILL.read_text(encoding="utf-8")
    assert "dashboard.html" not in src
    assert "shipment-detail.html" not in src
