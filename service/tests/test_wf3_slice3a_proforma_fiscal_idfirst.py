"""WF-3 Slice 3A — proforma FISCAL create uses the canonical contractor.id.

Slice 2A made the proforma *preview* resolve id-first (branch 0-pre in
``routes_proforma._resolve_customer``). But the fiscal payload builder,
``_build_proforma_request``, re-resolved the customer by NAME only
(``_resolve_customer(client_name)`` — no contractor.id), so a passing id-first
preview could still build a payload against a name-resolved (or missing)
contractor. Slice 3A threads the operator-selected ``client_contractor_id`` from
the draft into ``_build_proforma_request`` → ``_resolve_customer`` so the fiscal
payload's contractor.id equals the operator's selection whenever it is present
and resolvable, echoed VERBATIM (never a different id), and falls back to the
UNCHANGED name chain when the id is absent or unresolvable.

Safety gate pinned here (STOP conditions from the slice brief):
  * the fiscal payload can NEVER use a contractor.id different from the
    operator-selected one (TestFiscalPayloadUsesIdFirst),
  * no name-fallback branch is removed (TestNoRemovalNoScopeCreep),
  * no invoice-conversion / reservation / customer-creation logic is added.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_proforma as rp  # noqa: E402


def _fake_record(name="Canonical Name", source="customer_master", contractor_id="IGNORED"):
    # Mirrors the canonical resolver record shape. `contractor_id` is present on
    # purpose: branch 0-pre must IGNORE it and echo the supplied cid instead.
    return {"contractor_id": contractor_id, "name": name,
            "nip": "PL999", "country": "PL", "source": source}


class _StopAtCM(Exception):
    """Sentinel raised by the patched get_customer_master to halt the heavy
    payload build right after the contractor.id has been resolved."""


class TestFiscalPayloadUsesIdFirst:
    """Behavioural proof: the contractor.id that flows into the fiscal payload
    (the argument to get_customer_master, which drives VAT/series/CM) equals the
    operator-selected client_contractor_id whenever present and resolvable."""

    def _run(self, *, cir_return=..., cir_side_effect=None, cid, client_name="Typed Display Name"):
        captured = {}

        def _spy_cm(_dbpath, contractor_id):
            captured["contractor_id"] = contractor_id
            raise _StopAtCM()

        cir_patch = (
            patch.object(rp._cir, "resolve_by_contractor_id", side_effect=cir_side_effect)
            if cir_side_effect is not None
            else patch.object(rp._cir, "resolve_by_contractor_id", return_value=cir_return)
        )
        with cir_patch, patch.object(rp, "get_customer_master", _spy_cm):
            with pytest.raises((_StopAtCM, ValueError)) as exc:
                rp._build_proforma_request(
                    {"client_name": client_name, "batch_id": None},
                    client_contractor_id=cid,
                )
        return captured, exc

    def test_cid_present_and_resolvable_payload_uses_supplied_id(self):
        captured, exc = self._run(cir_return=_fake_record(), cid="777")
        assert exc.type is _StopAtCM               # reached the payload build
        assert captured["contractor_id"] == "777"  # exactly the operator's selection

    def test_resolver_record_carries_different_id_payload_still_uses_supplied(self):
        # STOP condition: even when the canonical record carries a DIFFERENT id,
        # the fiscal payload must still use the operator-supplied cid.
        captured, exc = self._run(
            cir_return=_fake_record(source="wfirma_customer_mirror",
                                    contractor_id="999-DIFFERENT"),
            cid="777",
        )
        assert exc.type is _StopAtCM
        assert captured["contractor_id"] == "777"
        assert captured["contractor_id"] != "999-DIFFERENT"

    def test_cid_missing_uses_name_fallback_unchanged(self):
        # No cid → branch 0-pre skipped (resolver never consulted) → name chain
        # (uninitialised wfdb / unknown name) → ValueError, exactly as before 3A.
        with patch.object(rp._cir, "resolve_by_contractor_id") as m, \
             patch.object(rp, "get_customer_master") as cm:
            with pytest.raises(ValueError):
                rp._build_proforma_request(
                    {"client_name": "ZZ Nonexistent Slice3A Client", "batch_id": None},
                    client_contractor_id="",
                )
        m.assert_not_called()   # id-first path never entered
        cm.assert_not_called()  # name miss raises before customer-master lookup

    def test_cid_unresolved_falls_back_to_name_unchanged(self):
        # cid supplied but canonical resolver returns None → branch 0-pre falls
        # through → same name-miss ValueError as the legacy path (unchanged).
        with patch.object(rp._cir, "resolve_by_contractor_id", return_value=None), \
             patch.object(rp, "get_customer_master") as cm:
            with pytest.raises(ValueError):
                rp._build_proforma_request(
                    {"client_name": "ZZ Nonexistent Slice3A Client", "batch_id": None},
                    client_contractor_id="404",
                )
        cm.assert_not_called()

    def test_resolver_exception_falls_back_without_crash(self):
        # A resolver failure must never crash create; it falls through to the
        # existing name chain (which here misses → ValueError, not RuntimeError).
        with patch.object(rp._cir, "resolve_by_contractor_id",
                          side_effect=RuntimeError("db locked")), \
             patch.object(rp, "get_customer_master") as cm:
            with pytest.raises(ValueError):
                rp._build_proforma_request(
                    {"client_name": "ZZ Nonexistent Slice3A Client", "batch_id": None},
                    client_contractor_id="500",
                )
        cm.assert_not_called()


class TestThreadingWiring:
    """Source-level pins for the exact call path the brief names:
    create → _build_proforma_request → _resolve_customer."""

    def test_build_proforma_request_accepts_client_contractor_id(self):
        params = inspect.signature(rp._build_proforma_request).parameters
        assert "client_contractor_id" in params
        assert params["client_contractor_id"].default == ""  # additive, optional

    def test_build_proforma_request_threads_cid_into_resolver(self):
        src = inspect.getsource(rp._build_proforma_request)
        assert "_resolve_customer(" in src
        assert "client_contractor_id=(client_contractor_id or \"\")" in src \
            or "client_contractor_id=(client_contractor_id or '')" in src

    def test_fiscal_contractor_id_is_the_resolver_output(self):
        # The payload's contractor id must come from the resolver result, so the
        # threaded id actually reaches the wFirma payload (not a separate lookup).
        src = inspect.getsource(rp._build_proforma_request)
        assert 'contractor_id = resolution["wfirma_customer_id"]' in src

    def test_create_call_site_passes_draft_selected_cid(self):
        src = inspect.getsource(rp)
        assert 'client_contractor_id=getattr(draft, "client_contractor_id", "") or ""' in src


class TestNoRemovalNoScopeCreep:
    """No name branch removed; no invoice/reservation/customer-create introduced."""

    def test_no_name_fallback_branch_removed(self):
        src = inspect.getsource(rp._resolve_customer)
        # The id-first branch and every legacy name branch must still be present.
        assert "0-pre" in src                       # id-first branch intact
        assert "0a." in src                         # per-document authority intact
        assert "customer_master" in src.lower()     # Customer Master name match intact
        assert "wfirma_customers" in src            # legacy cache fallback intact

    def test_build_proforma_request_adds_no_customer_creation(self):
        src = inspect.getsource(rp._build_proforma_request)
        for forbidden in ("create_customer(", "create_contractor(",
                          "wfirma_create_customer"):
            assert forbidden not in src

    def test_build_proforma_request_adds_no_reservation_logic(self):
        src = inspect.getsource(rp._build_proforma_request)
        for forbidden in ("create_reservation(", "reservation_worker",
                          "wfirma_reservation"):
            assert forbidden not in src

    def test_build_proforma_request_adds_no_invoice_conversion(self):
        src = inspect.getsource(rp._build_proforma_request).lower()
        for forbidden in ("convert_to_invoice", "convert-to-invoice",
                          "invoices/add", "faktura"):
            assert forbidden not in src

    def test_authority_separation_id_first_uses_canonical_resolver(self):
        # The id-first path must route through _resolve_customer (which owns the
        # canonical _cir resolver) — not a new direct wFirma customer API call.
        src = inspect.getsource(rp._build_proforma_request)
        assert "_resolve_customer(" in src
        # This slice introduces no NEW customer-creating wFirma call.
        assert ".create_customer(" not in src
