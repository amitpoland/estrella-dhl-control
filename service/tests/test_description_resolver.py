"""
test_description_resolver.py
==============================
Tests for the shared description resolver: lookup, write_mapping, _tokenize,
_suggest_material_pl, and the engine's new resolved_facts parameter.

Canonical governance rule pinned throughout:
  Known token (in DB or GOLD_PURITY) → render
  Unknown token                       → Inbox proposal, empty suggestion, human decides

Authority separation pinned:
  resolver.lookup() → facts
  engine.normalize_item_description(resolved_facts=facts) → wording (no re-parse)
  description_corrections (shipment scope) ← separate authority from resolver (global scope)
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

# Repo root on sys.path (customs_description_engine lives there)
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import customs_description_engine as cde  # noqa: E402

BATCH_ID = "SHIPMENT_TEST_RESOLVER"
NOW_ISO  = datetime.now(timezone.utc).isoformat()


# ── Fixture: isolated in-memory DB for resolver ───────────────────────────────

@pytest.fixture()
def resolver_db(tmp_path, monkeypatch):
    """Patch _DB_PATH in description_resolver to an isolated temp DB."""
    db_file = tmp_path / "master_data.sqlite"
    from app.services import description_resolver as dr
    monkeypatch.setattr(dr, "_DB_PATH", db_file)
    # Also patch the import inside _ensure_table so init_db uses the same path
    original_ensure = dr._ensure_table

    def _patched_ensure():
        from app.services.master_data_db import init_db
        init_db(db_file)

    monkeypatch.setattr(dr, "_ensure_table", _patched_ensure)
    return db_file, dr


# ── Engine: resolved_facts parameter ─────────────────────────────────────────

class TestEngineResolvedFacts:
    """The engine must not re-parse metal/purity when resolved_facts is provided."""

    def test_resolved_facts_bypasses_gold_purity(self):
        """Engine uses facts directly; does not scan GOLD_PURITY from raw text."""
        facts = {
            "canonical_metal": "PT960",
            "material_pl":     "platyna proby 960",
            "purity_gen":      "platyny proby 960",
        }
        r = cde.normalize_item_description(
            "PCS, PT960 Premium Platinum, Plain Ring",
            item_type="ring",
            resolved_facts=facts,
        )
        assert r["material_pl"] == "platyna proby 960", (
            f"Engine must use resolved_facts, got: {r['material_pl']!r}"
        )
        assert "platyny proby 960" in r["polish_customs_description"], (
            f"Engine must use purity_gen from facts: {r['polish_customs_description']!r}"
        )

    def test_no_resolved_facts_uses_gold_purity(self):
        """Original path unchanged: PT950 resolves via GOLD_PURITY."""
        r = cde.normalize_item_description(
            "PCS, PT950 Platinum, Plain Ring", item_type="ring",
        )
        assert r["material_pl"] == "platyna próby 950"

    def test_unknown_without_facts_produces_forbidden(self):
        """PT960 without resolved_facts falls through to 'metal szlachetny'."""
        r = cde.normalize_item_description(
            "PCS, PT960 Platinum, Plain Ring", item_type="ring",
        )
        assert r["material_pl"] == "metal szlachetny"

    def test_resolved_facts_still_parses_stones(self):
        """Engine still parses stones from raw text even when facts provided."""
        facts = {"canonical_metal": "PT960", "material_pl": "platyna proby 960",
                 "purity_gen": "platyny proby 960"}
        r = cde.normalize_item_description(
            "PCS, PT960 Platinum, Diamond Ring", item_type="ring", resolved_facts=facts,
        )
        # Stones detected from raw text
        assert "diament" in r["polish_customs_description"].lower() or \
               "diamond"  in r["polish_customs_description"].lower() or \
               "diament"  in (r.get("stones_pl") or "").lower(), (
            f"Stones must still be parsed from raw text: {r}"
        )

    def test_resolved_facts_none_default(self):
        """resolved_facts=None (default) leaves existing behaviour unchanged."""
        r1 = cde.normalize_item_description("18KT Gold Ring", item_type="ring")
        r2 = cde.normalize_item_description("18KT Gold Ring", item_type="ring",
                                            resolved_facts=None)
        assert r1["material_pl"] == r2["material_pl"]


# ── Resolver: lookup ──────────────────────────────────────────────────────────

class TestResolverLookup:

    def test_lookup_miss_returns_none(self, resolver_db):
        _, dr = resolver_db
        assert dr.lookup("PT960") is None

    def test_lookup_hit_returns_facts(self, resolver_db):
        db_file, dr = resolver_db
        _seed_mapping(db_file, token="PT960", material_pl="platyna proby 960",
                      purity_gen="platyny proby 960", canonical_metal="platinum", purity="960")
        facts = dr.lookup("PT960")
        assert facts is not None
        assert facts["material_pl"] == "platyna proby 960"
        assert facts["purity_gen"]  == "platyny proby 960"

    def test_lookup_inactive_row_returns_none(self, resolver_db):
        db_file, dr = resolver_db
        _seed_mapping(db_file, token="INACTIVE_TOKEN", material_pl="foo", active=0)
        assert dr.lookup("INACTIVE_TOKEN") is None

    def test_lookup_supplier_scoped_beats_global(self, resolver_db):
        db_file, dr = resolver_db
        _seed_mapping(db_file, token="TOK", material_pl="global_value", supplier_scope=None)
        _seed_mapping(db_file, token="TOK", material_pl="ejl_value",
                      supplier_scope="ejl", row_id=str(uuid.uuid4()))
        # EJL scope wins
        assert dr.lookup("TOK", supplier_scope="ejl")["material_pl"] == "ejl_value"
        # No scope → global
        assert dr.lookup("TOK")["material_pl"] == "global_value"

    def test_lookup_global_hits_for_all_suppliers(self, resolver_db):
        db_file, dr = resolver_db
        _seed_mapping(db_file, token="GLOBAL_TOK", material_pl="global_value",
                      supplier_scope=None)
        assert dr.lookup("GLOBAL_TOK", "ejl")["material_pl"]           == "global_value"
        assert dr.lookup("GLOBAL_TOK", "global_jewellery")["material_pl"] == "global_value"
        assert dr.lookup("GLOBAL_TOK")["material_pl"]                  == "global_value"

    def test_lookup_scoped_misses_for_other_supplier(self, resolver_db):
        db_file, dr = resolver_db
        _seed_mapping(db_file, token="EJL_ONLY", material_pl="ejl_value",
                      supplier_scope="ejl")
        assert dr.lookup("EJL_ONLY", "global_jewellery") is None
        assert dr.lookup("EJL_ONLY") is None


# ── Resolver: _suggest_material_pl ───────────────────────────────────────────

class TestSuggestMaterialPl:

    def test_known_token_returns_suggestion(self):
        from app.services.description_resolver import _suggest_material_pl
        # PT950 is in GOLD_PURITY
        s = _suggest_material_pl("PT950")
        assert s is not None and "platyna" in s.lower()

    def test_unknown_token_returns_none(self):
        from app.services.description_resolver import _suggest_material_pl
        # PT960 is NOT in GOLD_PURITY — system declines to guess
        assert _suggest_material_pl("PT960") is None

    def test_unknown_metal_word_returns_none(self):
        from app.services.description_resolver import _suggest_material_pl
        assert _suggest_material_pl("PLATINUM") is None

    def test_gold_known_token(self):
        from app.services.description_resolver import _suggest_material_pl
        assert _suggest_material_pl("18KT") is not None


# ── Resolver: write_mapping ───────────────────────────────────────────────────

class TestWriteMapping:

    def _base_kwargs(self) -> Dict[str, Any]:
        return dict(
            token="PT960", material_pl="platyna proby 960",
            approved_by="test_operator", approved_at=NOW_ISO,
            source_proposal_id=str(uuid.uuid4()),
            source_text="PCS, PT960 Platinum, Plain Ring",
            canonical_metal="platinum", purity="960",
            purity_gen="platyny proby 960", confidence="high",
        )

    def test_write_then_lookup(self, resolver_db):
        db_file, dr = resolver_db
        dr.write_mapping(**self._base_kwargs())
        facts = dr.lookup("PT960")
        assert facts is not None
        assert facts["material_pl"] == "platyna proby 960"

    def test_write_requires_approved_by(self, resolver_db):
        _, dr = resolver_db
        kwargs = self._base_kwargs()
        kwargs["approved_by"] = ""
        with pytest.raises(ValueError, match="approved_by"):
            dr.write_mapping(**kwargs)

    def test_write_requires_source_proposal_id(self, resolver_db):
        _, dr = resolver_db
        kwargs = self._base_kwargs()
        kwargs["source_proposal_id"] = ""
        with pytest.raises(ValueError, match="source_proposal_id"):
            dr.write_mapping(**kwargs)

    def test_write_requires_source_text(self, resolver_db):
        _, dr = resolver_db
        kwargs = self._base_kwargs()
        kwargs["source_text"] = ""
        with pytest.raises(ValueError, match="source_text"):
            dr.write_mapping(**kwargs)

    def test_write_requires_material_pl(self, resolver_db):
        _, dr = resolver_db
        kwargs = self._base_kwargs()
        kwargs["material_pl"] = ""
        with pytest.raises(ValueError, match="material_pl"):
            dr.write_mapping(**kwargs)

    def test_duplicate_supersedes(self, resolver_db):
        """Second write for same token deactivates old row and inserts new."""
        db_file, dr = resolver_db
        dr.write_mapping(**self._base_kwargs())
        kwargs2 = self._base_kwargs()
        kwargs2["material_pl"] = "platyna proby 960 updated"
        dr.write_mapping(**kwargs2)
        facts = dr.lookup("PT960")
        assert facts["material_pl"] == "platyna proby 960 updated"


# ── Approval: global_mapping scope writes to resolver ────────────────────────

class TestApprovalGlobalMappingScope:

    def _make_proposal(self, token: str = "PT960") -> Dict[str, Any]:
        return {
            "proposal_id":   str(uuid.uuid4()),
            "type":          "customs_description_mismatch",
            "channel":       "ai_reverification",
            "status":        "pending_review",
            "product_code":  "EJL/TEST/1",
            "invoice_no":    "EJL/TEST",
            "data": {
                "source":          "PCS, PT960 Platinum, Plain Ring",
                "token_detected":  token,
                "confidence":      "high",
            },
        }

    def test_global_mapping_approval_calls_write_mapping(self, resolver_db, monkeypatch):
        from app.api.routes_action_proposals import ApproveBody, DescriptionCorrection
        from app.api import routes_action_proposals as rap

        batch_id = BATCH_ID
        prop = self._make_proposal()
        audit = {"batch_id": batch_id, "action_proposals": [prop]}

        _, dr = resolver_db
        # Patch resolver write_mapping to assert it's called with correct args
        written: Dict = {}

        def _capture_write(**kwargs):
            written.update(kwargs)
            return str(uuid.uuid4())

        monkeypatch.setattr(dr, "write_mapping", _capture_write)
        monkeypatch.setattr(
            "app.api.routes_action_proposals.write_mapping",
            _capture_write, raising=False,
        )
        monkeypatch.setattr(rap, "_resolve_proposal",
                            lambda pid: (batch_id, audit, prop))
        monkeypatch.setattr(rap, "_save_audit", lambda bid, a: None)
        monkeypatch.setattr(rap, "tl", MagicMock())

        # Patch the import inside approve_proposal
        import importlib
        with patch("app.services.description_resolver.write_mapping", _capture_write):
            body = ApproveBody(
                approved_by="test_operator",
                scope="global_mapping",
                correction=DescriptionCorrection(
                    material_pl="platyna proby 960",
                    purity_gen="platyny proby 960",
                    canonical_metal="platinum",
                    purity="960",
                ),
            )
            result = rap.approve_proposal(prop["proposal_id"], body)

        assert result["status"] == "approved"
        applied = result.get("correction_applied", {})
        assert applied.get("scope") == "global_mapping"
        assert applied.get("token") == "PT960"

    def test_shipment_scope_does_not_write_resolver(self, resolver_db, monkeypatch):
        """scope='shipment' must write audit['description_corrections'], NOT the DB."""
        from app.api.routes_action_proposals import ApproveBody, DescriptionCorrection
        from app.api import routes_action_proposals as rap

        batch_id = BATCH_ID
        prop = self._make_proposal()
        audit = {"batch_id": batch_id, "action_proposals": [prop]}

        db_written = []

        def _should_not_be_called(**kwargs):
            db_written.append(kwargs)
            raise AssertionError("write_mapping must not be called for scope=shipment")

        monkeypatch.setattr(rap, "_resolve_proposal",
                            lambda pid: (batch_id, audit, prop))
        monkeypatch.setattr(rap, "_save_audit", lambda bid, a: None)
        monkeypatch.setattr(rap, "tl", MagicMock())

        with patch("app.services.description_resolver.write_mapping",
                   _should_not_be_called):
            body = ApproveBody(
                approved_by="test_operator",
                scope="shipment",  # shipment scope
                correction=DescriptionCorrection(material_pl="platyna proby 960"),
            )
            result = rap.approve_proposal(prop["proposal_id"], body)

        assert result["status"] == "approved"
        applied = result.get("correction_applied", {})
        assert applied.get("scope") == "shipment"
        # Shipment correction written to audit
        assert "description_corrections" in audit
        assert audit["description_corrections"]["EJL/TEST/1"]["material_pl"] == "platyna proby 960"
        # DB was NOT written
        assert db_written == []


# ── Integration: resolver → engine → correct output ──────────────────────────

class TestResolverEngineIntegration:

    def test_pt960_in_db_renders_correctly(self, resolver_db):
        """After PT960 is approved as global_mapping, the checker should
        use the resolver and the engine should render correctly."""
        db_file, dr = resolver_db
        dr.write_mapping(
            token="PT960", material_pl="platyna proby 960",
            approved_by="op", approved_at=NOW_ISO,
            source_proposal_id="test-pid", source_text="PCS, PT960 Platinum Ring",
            canonical_metal="platinum", purity="960",
            purity_gen="platyny proby 960",
        )
        facts = dr.lookup("PT960")
        assert facts is not None

        r = cde.normalize_item_description(
            "PCS, PT960 Premium Platinum, Plain Ring",
            item_type="ring", resolved_facts=facts,
        )
        assert r["material_pl"] == "platyna proby 960"
        assert "platyny proby 960" in r["polish_customs_description"]

    def test_checker_uses_resolver_hit_no_proposal(self, resolver_db, tmp_path):
        """Once PT960 is in the DB, checker must NOT emit a proposal for it."""
        db_file, dr = resolver_db
        dr.write_mapping(
            token="PT960", material_pl="platyna proby 960",
            approved_by="op", approved_at=NOW_ISO,
            source_proposal_id="test-pid", source_text="PT960 test",
        )
        line = {
            "description":   "PCS, PT960 Platinum, Plain Ring",
            "product_code":  "EJL/T/1",
            "invoice_no":    "EJL/T",
            "line_position": 1,
            "quantity":      1.0,
            "total_value":   100.0,
        }
        from app.services.customs_desc_checker import check_customs_description_accuracy
        audit = {"batch_id": BATCH_ID, "action_proposals": []}

        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert proposals == [], (
            f"Resolver hit for PT960 — no proposal expected, got: {proposals}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_mapping(
    db_file: pathlib.Path,
    token: str,
    material_pl: str,
    purity_gen: str = "",
    canonical_metal: str = "",
    purity: str = "",
    supplier_scope=None,
    active: int = 1,
    row_id: str = None,
) -> None:
    from app.services.master_data_db import init_db
    init_db(db_file)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO description_mappings
               (id, token, canonical_metal, purity, material_pl, purity_gen,
                approved_by, approved_at, source_proposal_id, source_text,
                confidence, supplier_scope, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'seed', 'now', 'seed-pid', 'seed-src',
                       'high', ?, ?, 'now')""",
            (
                row_id or str(uuid.uuid4()),
                token.upper(), canonical_metal or None, purity or None,
                material_pl, purity_gen or material_pl,
                supplier_scope, active,
            ),
        )
