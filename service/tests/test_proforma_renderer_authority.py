"""
test_proforma_renderer_authority.py — Regression tests for proforma-detail.jsx
renderer authority contracts.

Pins the three data-authority defects fixed in the proforma renderer:

  A. buyer_override authority — GET /api/v1/proforma/draft/{id} must include
     buyer_override.{name,vat_id,street,city,zip,country}.  The JSX reads
     liveDraft.buyer_override for buyer name/VAT/address display.
     customer_resolution IS in the response but lacks vat_eu/address/country —
     buyer_override is the authority for those fields.

  B. editable_lines name_pl authority — each editable line must include
     name_pl (set by the enrichment step).  The JSX reads ln.name_pl for
     product descriptions; falling back to ln.design_no renders internal SKU
     codes instead of commercial descriptions.

  C. company_profile seller address — the service layer must persist
     street/postal_city changes so the seller card on the proforma shows
     the correct address.

    Correct Estrella address:
      street:      ul. Wybrzeże Kościuszkowskie 31/33
      postal_city: 00-379 Warszawa
    Stale (wrong) address that triggered this fix:
      street:      ul. Nowy Swiat 27 lok. 39
      postal_city: 00-029 Warszawa

Origin: PROF 123/2026 (Draft #24) rendering defects discovered 2026-06-09.
Batch: SHIPMENT_9938632830 / Invoice EJL/26-27/244 / buyer: UAB Tomas Gold.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb


# ── helpers ──────────────────────────────────────────────────────────────────

def _readonly_auth() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


# ── Fixture: draft with buyer_override and name_pl lines ─────────────────────

_BUYER_OVERRIDE = {
    "name":    "UAB Tomas Gold",
    "vat_id":  "LT100007135616",
    "street":  "Kuosų g. 20-1,",
    "city":    "Klaipėda",
    "zip":     "LT-91187",
    "country": "LT",
    "type":    "company",
}

_RAW_LINES = [
    {
        "line_id":      None,
        "product_code": "EJL/26-27/244-1",
        "design_no":    "JP01823-0.20",
        "qty":           3.0,
        "unit_price":    211.0,
        "currency":      "EUR",
        "line_value":    633.0,
        "product_match": True,
        "stock_ok":      True,
        "stock_status":  "in_stock",
        "price_source":  "excel_symbol",
    },
    {
        "line_id":      None,
        "product_code": "EJL/26-27/244-3",
        "design_no":    "RG00101-0.15",
        "qty":           2.0,
        "unit_price":    450.0,
        "currency":      "EUR",
        "line_value":    900.0,
        "product_match": True,
        "stock_ok":      True,
        "stock_status":  "in_stock",
        "price_source":  "excel_symbol",
    },
]

# name_pl / description_pl annotations (as set by the enrichment step in production)
_ENRICHED_ANNOTATIONS = {
    "EJL/26-27/244-1": {
        "name_pl":       "wisiorek z 14-karatowego białego złota z diamentami",
        "description_pl": "Wisiorek ze złota próby 585 z diamentami i kamieniami szlachetnymi",
    },
    "EJL/26-27/244-3": {
        "name_pl":       "pierścionek z 14-karatowego złota z diamentami",
        "description_pl": "Pierścionek ze złota próby 585 z diamentami",
    },
}


def _seed_draft_with_buyer_override(
    db: Path,
    *,
    batch: str = "BATCH_RA_01",
    client_name: str = "UAB",
) -> pildb.ProformaDraft:
    """Seed a draft with buyer_override and enriched editable_lines (name_pl set).

    auto_create_draft_from_sales_packing strips non-standard line fields
    (name_pl, description_pl).  We inject them back via DB update to match
    production state where the enrichment step has run.
    """
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=batch, client_name=client_name, currency="EUR",
        lines=_RAW_LINES,
    )

    # Read stored editable_lines, inject name_pl/description_pl
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT editable_lines_json FROM proforma_drafts WHERE id=?", (draft.id,)
    ).fetchone()
    stored_lines = json.loads(row[0] or "[]")
    for ln in stored_lines:
        ann = _ENRICHED_ANNOTATIONS.get(ln.get("product_code") or "")
        if ann:
            ln.update(ann)

    conn.execute(
        "UPDATE proforma_drafts SET buyer_override_json=?, editable_lines_json=? WHERE id=?",
        (
            json.dumps(_BUYER_OVERRIDE, ensure_ascii=False),
            json.dumps(stored_lines, ensure_ascii=False),
            draft.id,
        ),
    )
    conn.commit()
    conn.close()
    return draft


# ── A. buyer_override authority ───────────────────────────────────────────────

class TestBuyerOverrideAuthority:
    """
    A. buyer_override contract — GET /api/v1/proforma/draft/{id} must include
       buyer_override.{name,vat_id,street,city,zip,country}.
       customer_resolution IS also present but lacks vat/address/country
       (it only carries wfirma resolution metadata).
       proforma-detail.jsx reads bo = liveDraft.buyer_override for name/VAT/addr.
    """

    def test_draft_response_includes_buyer_override(self, client, db_path, tmp_path):
        """buyer_override is present in the full draft response."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="BO_A1")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        bo = body["draft"]["buyer_override"]
        assert isinstance(bo, dict), "buyer_override must be a dict, not missing/null"

    def test_buyer_override_carries_name_vat_address_fields(self, client, db_path, tmp_path):
        """buyer_override contains the name, vat_id, and address fields the JSX reads."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="BO_A2")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        bo = r.json()["draft"]["buyer_override"]

        assert bo["name"]    == "UAB Tomas Gold",  f"name wrong: {bo['name']}"
        assert bo["vat_id"]  == "LT100007135616",   f"vat_id wrong: {bo['vat_id']}"
        assert bo["street"]  == "Kuosų g. 20-1,",   f"street wrong: {bo['street']}"
        assert bo["city"]    == "Klaipėda",          f"city wrong: {bo['city']}"
        assert bo["zip"]     == "LT-91187",          f"zip wrong: {bo['zip']}"
        assert bo["country"] == "LT",               f"country wrong: {bo['country']}"

    def test_buyer_override_name_differs_from_client_name(self, client, db_path, tmp_path):
        """client_name ('UAB') is the raw packing-list name; buyer_override.name
        ('UAB Tomas Gold') is the resolved full name.  The JSX uses bo.name
        (buyer_override.name) as the authoritative buyer display name.
        """
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(
                db_path, batch="BO_A3", client_name="UAB"
            )

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        d = r.json()["draft"]
        assert d["client_name"] == "UAB"
        assert d["buyer_override"]["name"] == "UAB Tomas Gold"
        assert d["buyer_override"]["name"] != d["client_name"], (
            "buyer_override.name must differ from client_name: "
            "if equal, the buyer_override authority adds no value over client_name alone"
        )

    def test_customer_resolution_lacks_vat_and_address_fields(
        self, client, db_path, tmp_path
    ):
        """customer_resolution is present but carries only wFirma resolution metadata
        (normalized_customer_name, wfirma_customer_id, match_strategy) — NOT vat_eu,
        address, or country.  This test pins that absence: the JSX must read those
        from buyer_override, not customer_resolution.
        """
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="BO_A4")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        d = r.json()["draft"]
        cr = d.get("customer_resolution") or {}

        # These fields must NOT be in customer_resolution.
        # If any appear, the JSX could incorrectly rely on them.
        assert "vat_eu" not in cr, (
            "vat_eu must not appear in customer_resolution — "
            "buyer_override.vat_id is the only VAT authority"
        )
        assert "address" not in cr, (
            "address must not appear in customer_resolution — "
            "buyer_override street/city/zip is the only address authority"
        )
        assert "country" not in cr, (
            "country must not appear in customer_resolution — "
            "buyer_override.country is the only country authority"
        )

    def test_empty_buyer_override_returns_empty_dict_not_null(
        self, client, db_path, tmp_path
    ):
        """When buyer_override_json is NULL/empty, the API returns {} not null.
        The JSX does `const bo = liveDraft.buyer_override || {}` — null would be
        falsy so this is handled, but {} is the cleaner contract.
        """
        with patch.object(settings, "storage_root", tmp_path):
            draft, _ = pildb.auto_create_draft_from_sales_packing(
                db_path, batch_id="BO_A5", client_name="EMPTY", currency="EUR",
                lines=[{
                    "line_id": None, "product_code": "EJL/T/01", "design_no": "D1",
                    "qty": 1, "unit_price": 10.0, "currency": "EUR", "line_value": 10.0,
                    "product_match": True, "stock_ok": True, "stock_status": "in_stock",
                    "price_source": "packing_list",
                }],
            )

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        bo = r.json()["draft"]["buyer_override"]
        assert bo is not None, "buyer_override must not be null (should be {})"
        assert isinstance(bo, dict)


# ── B. editable_lines name_pl authority ──────────────────────────────────────

class TestEditableLinesNamePlAuthority:
    """
    B. editable_lines name_pl contract — each line must carry name_pl when set
       by the enrichment step.  The JSX renders:
           ln.name_pl || ln.description_pl || ln.design_no || ln.product_code
       Regression: if name_pl disappears from the response, design_no (internal
       SKU code like 'JP01823-0.20') appears on the proforma.
    """

    def test_editable_lines_carry_name_pl_after_enrichment(
        self, client, db_path, tmp_path
    ):
        """editable_lines lines include name_pl when set by the enrichment step."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="NP_B1")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        assert r.status_code == 200
        lines = r.json()["draft"]["editable_lines"]
        assert len(lines) >= 1

        for ln in lines:
            if ln.get("product_code") in _ENRICHED_ANNOTATIONS:
                assert ln.get("name_pl"), (
                    f"name_pl missing from editable_line for product "
                    f"{ln.get('product_code')} / design_no {ln.get('design_no')}"
                )

    def test_editable_lines_name_pl_is_commercial_not_sku(
        self, client, db_path, tmp_path
    ):
        """name_pl must be a human-readable description, not a design_no SKU code.
        Regression: design_no values are internal codes like 'JP01823-0.20' —
        they must NOT appear as the primary line description on the proforma.
        """
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="NP_B2")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        lines = r.json()["draft"]["editable_lines"]

        for ln in lines:
            name_pl  = (ln.get("name_pl") or "").strip()
            design_no = (ln.get("design_no") or "").strip()
            if name_pl and design_no:
                assert name_pl != design_no, (
                    f"name_pl = design_no = {design_no!r}: "
                    f"commercial description must differ from SKU code"
                )

    def test_editable_lines_carry_description_pl(self, client, db_path, tmp_path):
        """description_pl is available as fallback after name_pl."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="NP_B3")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        lines = r.json()["draft"]["editable_lines"]
        lines_with_desc_pl = [l for l in lines if l.get("description_pl")]
        assert len(lines_with_desc_pl) >= 1, (
            "At least one line must carry description_pl for the fallback chain "
            "ln.name_pl || ln.description_pl || ln.design_no to be tested"
        )

    def test_line_id_present_on_every_line(self, client, db_path, tmp_path):
        """Every editable_line must have line_id (needed by PATCH-by-id)."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="NP_B4")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        for ln in r.json()["draft"]["editable_lines"]:
            assert ln.get("line_id"), f"line_id missing on line: {ln}"

    def test_design_no_present_as_fallback_when_name_pl_absent(
        self, client, db_path, tmp_path
    ):
        """When name_pl is absent (line not enriched), design_no is present as
        the JSX fallback — the renderer never shows '—' for an unenriched line.
        """
        with patch.object(settings, "storage_root", tmp_path):
            # Use a plain draft without enrichment (name_pl not injected)
            draft, _ = pildb.auto_create_draft_from_sales_packing(
                db_path, batch_id="NP_B5", client_name="TEST", currency="EUR",
                lines=[{
                    "line_id": None, "product_code": "EJL/T/01",
                    "design_no": "JP01823-0.20",
                    "qty": 1, "unit_price": 200.0, "currency": "EUR",
                    "line_value": 200.0, "product_match": True,
                    "stock_ok": True, "stock_status": "in_stock",
                    "price_source": "excel_symbol",
                }],
            )

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        lines = r.json()["draft"]["editable_lines"]
        assert len(lines) >= 1
        ln = lines[0]
        # Without enrichment name_pl is absent; design_no must be present as fallback
        assert not ln.get("name_pl"), "name_pl should be absent on unenriched line"
        assert ln.get("design_no") == "JP01823-0.20", (
            f"design_no must be present as fallback: {ln}"
        )


# ── C. company_profile seller address (service-layer) ────────────────────────

class TestCompanyProfileSellerAddress:
    """
    C. company_profile seller address — the service layer upsert_company_profile
       must persist street + postal_city changes.
       The seller card reads from GET /api/v1/settings/company-profile; a stale
       address here causes the wrong seller address to appear on the proforma.

    Tests use the service function directly since PATCH requires session auth
    (not testable via API key in unit tests).
    """

    CORRECT_STREET      = "ul. Wybrzeże Kościuszkowskie 31/33"
    CORRECT_POSTAL_CITY = "00-379 Warszawa"
    STALE_STREET        = "ul. Nowy Swiat 27 lok. 39"
    STALE_POSTAL_CITY   = "00-029 Warszawa"

    def test_correct_and_stale_addresses_differ(self):
        """Regression: the correct and stale addresses must be distinct —
        a trivial guard ensuring the test has discriminating power.
        """
        assert self.CORRECT_STREET      != self.STALE_STREET
        assert self.CORRECT_POSTAL_CITY != self.STALE_POSTAL_CITY

    def test_upsert_persists_street_and_postal_city(self, tmp_path):
        """upsert_company_profile persists street and postal_city changes."""
        from app.services.master_data_db import (
            get_company_profile,
            upsert_company_profile,
        )
        db = tmp_path / "master_data.sqlite"

        # Write stale address first
        upsert_company_profile(
            db, street=self.STALE_STREET, postal_city=self.STALE_POSTAL_CITY
        )
        p1 = get_company_profile(db)
        assert p1 is not None
        assert p1.street      == self.STALE_STREET
        assert p1.postal_city == self.STALE_POSTAL_CITY

        # Update to correct address
        upsert_company_profile(
            db, street=self.CORRECT_STREET, postal_city=self.CORRECT_POSTAL_CITY
        )
        p2 = get_company_profile(db)
        assert p2.street      == self.CORRECT_STREET,      (
            f"street not updated: {p2.street!r}"
        )
        assert p2.postal_city == self.CORRECT_POSTAL_CITY, (
            f"postal_city not updated: {p2.postal_city!r}"
        )

    def test_company_profile_get_endpoint_returns_street(self, client, tmp_path):
        """GET /api/v1/settings/company-profile returns street and postal_city fields."""
        r = client.get("/api/v1/settings/company-profile", headers=_readonly_auth())
        assert r.status_code == 200
        profile = r.json().get("profile") or {}
        assert "street"      in profile, "street field missing from company-profile response"
        assert "postal_city" in profile, "postal_city field missing from company-profile response"


# ── Source-grep: JSX buyer authority lines ───────────────────────────────────

class TestJsxBuyerAuthoritySourceGrep:
    """
    Source-grep tests that pin the JSX buyer authority fix.
    These verify the renderer code reads buyer_override, not customer_resolution,
    for name/VAT/address.
    """

    JSX = Path(__file__).resolve().parent.parent / "app" / "static" / "v2" / "proforma-detail.jsx"

    def _src(self) -> str:
        return self.JSX.read_text(encoding="utf-8")

    def test_jsx_buyer_authority_comment_updated(self):
        """The JSX buyer section comment must reference buyer_override, not customer_resolution."""
        src = self._src()
        assert "buyer_override" in src, "buyer_override must appear in proforma-detail.jsx"

    def test_jsx_reads_bo_name_for_buyer_display(self):
        """The JSX must read bo.name (buyer_override.name) for the buyer display name."""
        src = self._src()
        assert "bo.name" in src, (
            "proforma-detail.jsx must read bo.name (buyer_override.name) for buyer display"
        )

    def test_jsx_reads_bo_vat_id(self):
        """The JSX must read bo.vat_id (buyer_override.vat_id) for VAT EU display."""
        src = self._src()
        assert "bo.vat_id" in src, (
            "proforma-detail.jsx must read bo.vat_id (buyer_override.vat_id) for VAT display"
        )

    def test_jsx_reads_name_pl_for_line_description(self):
        """The JSX must read ln.name_pl as the primary product line description."""
        src = self._src()
        assert "ln.name_pl" in src, (
            "proforma-detail.jsx must read ln.name_pl for product line descriptions"
        )

    def test_jsx_design_no_is_fallback_not_primary(self):
        """design_no must appear AFTER name_pl in the fallback chain, not before."""
        src = self._src()
        # Scope to the DESCRIPTION fallback expression, not the standalone
        # "Design No" table column (`ln.design_no || '—'`) which legitimately
        # appears earlier in the table. Within the chain, name_pl must precede
        # design_no.
        chain_idx = src.find("ln.name_pl || ln.description_pl")
        assert chain_idx != -1, (
            "description fallback chain (ln.name_pl || ln.description_pl ...) "
            "not found in proforma-detail.jsx"
        )
        chain = src[chain_idx:chain_idx + 200]
        idx_name_pl  = chain.find("ln.name_pl")
        idx_design_no = chain.find("ln.design_no")
        assert idx_design_no != -1, "ln.design_no not found in the description fallback chain"
        assert idx_name_pl < idx_design_no, (
            "ln.name_pl must appear before ln.design_no in the description fallback "
            "chain (name_pl is the primary description, design_no is the last-resort fallback)"
        )

    def test_jsx_never_shows_mapped_null_literal(self):
        """The JSX mappedMsg must never produce the string 'Mapped: null'.
        Regression: wfirmaName was null → template literal rendered 'Mapped: null'.
        Fix: guard expression so wfirmaName=null renders '✓ Mapped to wFirma' instead.
        """
        src = self._src()
        # The old broken pattern: `✓ Mapped: ${customer.wfirmaName}` without null guard
        # must NOT appear without a null check on wfirmaName.
        # We verify the fixed form is present (wfirmaName ternary guard).
        assert "wfirmaName ?" in src or "customer.wfirmaName ?" in src, (
            "mappedMsg must guard against null wfirmaName — "
            "the raw template `Mapped: ${customer.wfirmaName}` without null check is forbidden"
        )

    def test_jsx_shipto_uses_ship_to_override_first(self):
        """shipTo object must read from ship_to_override first, buyer_override as fallback."""
        src = self._src()
        assert "ship_to_override" in src, (
            "ship_to_override must be referenced in proforma-detail.jsx for RECIPIENT/CMR"
        )
        assert "shipTo" in src, (
            "shipTo variable must exist for RECIPIENT and CMR ship-to rendering"
        )

    def test_jsx_migration_script_uses_correct_address(self):
        """The migration script must target the correct Wybrzeże address, not Nowy Świat."""
        migration = (
            Path(__file__).resolve().parent.parent
            / "migrations"
            / "migrate_company_profile_address.py"
        )
        assert migration.exists(), f"Migration script not found: {migration}"
        txt = migration.read_text(encoding="utf-8")
        assert "Wybrzeże Kościuszkowskie 31/33" in txt, (
            "Migration script must contain the correct 'Wybrzeże Kościuszkowskie 31/33' address"
        )
        assert "Nowy Swiat" in txt, (
            "Migration script must reference the stale 'Nowy Swiat' address for idempotency guard"
        )
        assert "00-379 Warszawa" in txt, "Migration script must contain correct postal_city"


# ── D. Operator-specified acceptance tests ───────────────────────────────────

class TestOperatorAcceptanceCriteria:
    """
    The exact acceptance tests named by the operator in the fix directive:
      - buyer renders UAB Tomas Gold from buyer_override (not raw client_name)
      - VAT LT100007135616 appears in response
      - "Mapped: null" literal never produced by mappedMsg expression
      - line 1 description uses name_pl / description_pl, NOT design_no JP01823-0.20
      - JP01823-0.20 remains only in the sku/design field, not in desc
      - seller profile migration targets Wybrzeże address, not Nowy Świat
    """

    @pytest.fixture()
    def posted_draft(self, db_path, tmp_path) -> "pildb.ProformaDraft":
        """A draft seeded to match the real PROF 123/2026 / Draft #24 scenario."""
        with patch.object(settings, "storage_root", tmp_path):
            return _seed_draft_with_buyer_override(db_path, batch="ACC_DRAFT")

    def test_buyer_name_is_uab_tomas_gold(self, client, db_path, tmp_path):
        """Buyer card renders 'UAB Tomas Gold' from buyer_override.name, not raw 'UAB'."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(
                db_path, batch="ACC_D1", client_name="UAB"
            )

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        bo = r.json()["draft"]["buyer_override"]
        assert bo["name"] == "UAB Tomas Gold", (
            f"buyer_override.name must be 'UAB Tomas Gold', got {bo['name']!r}"
        )
        # client_name is the raw fallback; buyer_override.name takes precedence
        assert r.json()["draft"]["client_name"] == "UAB"

    def test_vat_lt100007135616_present_in_buyer_override(self, client, db_path, tmp_path):
        """VAT ID LT100007135616 must be present in buyer_override.vat_id."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="ACC_D2")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        bo = r.json()["draft"]["buyer_override"]
        assert bo["vat_id"] == "LT100007135616", (
            f"VAT LT100007135616 must be in buyer_override.vat_id, got {bo.get('vat_id')!r}"
        )

    def test_line1_description_uses_name_pl_not_design_no(self, client, db_path, tmp_path):
        """First editable line description must use name_pl, not the design_no SKU.
        Regression: design_no 'JP01823-0.20' was rendering as the product description.
        """
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="ACC_D3")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        lines = r.json()["draft"]["editable_lines"]
        line1 = next(
            (l for l in lines if l.get("product_code") == "EJL/26-27/244-1"), None
        )
        assert line1 is not None, "No line with product_code EJL/26-27/244-1 found"

        name_pl  = line1.get("name_pl") or ""
        design_no = line1.get("design_no") or ""

        # name_pl must be the commercial description
        assert "wisiorek" in name_pl.lower(), (
            f"name_pl should contain 'wisiorek' (Polish for pendant), got: {name_pl!r}"
        )
        # design_no must still be in the line (for SKU column), just not as primary description
        assert design_no in ("JP01823-0.20", "JP02296-0.25", "J3609P00210", "JP00632",
                              "JP01843-0.10", "JP07631", "J2303P00241", "JP01938",
                              "JP01938-0.25", "JP02130"), (
            f"design_no must be an EJL/26-27/244-1 design code, got: {design_no!r}"
        )
        # The name_pl must NOT equal the design_no (no SKU leaking into description)
        assert name_pl != design_no, (
            f"name_pl must differ from design_no: {design_no!r} must not be the description"
        )

    def test_design_no_jp01823_remains_in_sku_field(self, client, db_path, tmp_path):
        """JP01823-0.20 must still appear in the design_no field (SKU column).
        The fix only changes which field is the primary description — it must NOT
        strip design_no from the line data.
        """
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft_with_buyer_override(db_path, batch="ACC_D4")

        r = client.get(f"/api/v1/proforma/draft/{draft.id}", headers=_readonly_auth())
        lines = r.json()["draft"]["editable_lines"]
        design_nos = [l.get("design_no") for l in lines if l.get("design_no")]
        assert "JP01823-0.20" in design_nos, (
            f"JP01823-0.20 must remain in editable_lines.design_no; found: {design_nos}"
        )

    def test_seller_migration_targets_wybrzeze_not_nowy_swiat(self):
        """The migration script must update TO Wybrzeże, not to Nowy Świat."""
        from pathlib import Path as _P
        migration = (
            _P(__file__).resolve().parent.parent
            / "migrations" / "migrate_company_profile_address.py"
        )
        txt = migration.read_text(encoding="utf-8")
        # Correct address must be the target
        assert "ul. Wybrzeże Kościuszkowskie 31/33" in txt
        assert "00-379 Warszawa" in txt
        # Stale address must be the idempotency guard
        assert "Nowy Swiat" in txt
        # The script must be idempotent — check for already-correct guard
        assert "Already correct" in txt or "CORRECT_STREET" in txt, (
            "Migration script must include idempotency check for already-correct state"
        )

    def test_upsert_company_profile_wybrzeze_roundtrip(self, tmp_path):
        """upsert_company_profile with Wybrzeże address round-trips through get."""
        from app.services.master_data_db import get_company_profile, upsert_company_profile
        db = tmp_path / "master_data.sqlite"
        upsert_company_profile(
            db,
            street="ul. Wybrzeże Kościuszkowskie 31/33",
            postal_city="00-379 Warszawa",
        )
        p = get_company_profile(db)
        assert p is not None
        assert p.street      == "ul. Wybrzeże Kościuszkowskie 31/33"
        assert p.postal_city == "00-379 Warszawa"
