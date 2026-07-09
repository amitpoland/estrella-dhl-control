"""WF-3 Slice 3B — proforma POST / CONVERT fiscal path uses the canonical contractor.id.

Slice 3A made the proforma *create* payload builder (`_build_proforma_request`)
id-first. The POST path uses a DIFFERENT builder, ``_build_proforma_request_from_draft``,
which re-resolved the customer by NAME only (``_resolve_customer(client_name)``), so a
draft that was approved/previewed id-first could still be POSTED to wFirma against a
name-resolved (or missing) contractor. Convert inherits the contractor.id from the posted
proforma XML, so fixing POST fixes convert too. Approve is local-only (no resolution).

Slice 3B threads the draft's operator-selected ``client_contractor_id`` (the draft is
already the sole argument to the builder) into ``_resolve_customer`` so the POST payload's
contractor.id equals the operator's selection whenever present and resolvable, echoed
VERBATIM (never a different id), falling back to the UNCHANGED name chain otherwise.

Safety gate pinned here (STOP conditions from the slice brief):
  * the POST payload can NEVER use a contractor.id different from the operator-selected one,
  * no name-fallback branch is removed,
  * no reservation / schema / DB / UI / customer-creation change.
"""
from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_proforma as rp  # noqa: E402


def _fake_record(name="Canonical Name", source="customer_master", contractor_id="IGNORED"):
    # The canonical resolver record; `contractor_id` is present on purpose — branch
    # 0-pre must IGNORE it and echo the supplied cid instead.
    return {"contractor_id": contractor_id, "name": name,
            "nip": "PL999", "country": "PL", "source": source}


def _draft(cid, *, client_name="Typed Display Name", currency="PLN"):
    """Minimal ProformaDraft-like object carrying exactly the fields the builder
    reads before the customer-resolution step."""
    return types.SimpleNamespace(
        client_name=client_name,
        currency=currency,
        client_contractor_id=cid,
        editable_lines_json=json.dumps(
            [{"qty": 1, "unit_price": 10, "product_code": "X", "currency": "PLN"}]
        ),
        service_charges_json="[]",
    )


class _StopAtCM(Exception):
    """Sentinel raised by the patched get_customer_master to halt the heavy payload
    build right after the contractor.id has been resolved."""


class TestPostPayloadUsesIdFirst:
    """Behavioural proof: the contractor.id flowing into the POST fiscal payload
    (the argument to get_customer_master, which drives VAT/series) equals the
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
                rp._build_proforma_request_from_draft(_draft(cid, client_name=client_name))
        return captured, exc

    def test_cid_present_and_resolvable_payload_uses_supplied_id(self):
        captured, exc = self._run(cir_return=_fake_record(), cid="777")
        assert exc.type is _StopAtCM
        assert captured["contractor_id"] == "777"

    def test_resolver_record_carries_different_id_payload_still_uses_supplied(self):
        # STOP condition: the record carries a DIFFERENT id; the POST payload must
        # still use the operator-supplied cid, never the record's.
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
        # (uninitialised wfdb / unknown name) → ValueError, exactly as before 3B.
        with patch.object(rp._cir, "resolve_by_contractor_id") as m, \
             patch.object(rp, "get_customer_master") as cm:
            with pytest.raises(ValueError):
                rp._build_proforma_request_from_draft(
                    _draft("", client_name="ZZ Nonexistent Slice3B Client")
                )
        m.assert_not_called()
        cm.assert_not_called()

    def test_cid_unresolved_falls_back_to_name_unchanged(self):
        with patch.object(rp._cir, "resolve_by_contractor_id", return_value=None), \
             patch.object(rp, "get_customer_master") as cm:
            with pytest.raises(ValueError):
                rp._build_proforma_request_from_draft(
                    _draft("404", client_name="ZZ Nonexistent Slice3B Client")
                )
        cm.assert_not_called()

    def test_resolver_exception_falls_back_without_crash(self):
        with patch.object(rp._cir, "resolve_by_contractor_id",
                          side_effect=RuntimeError("db locked")), \
             patch.object(rp, "get_customer_master") as cm:
            with pytest.raises(ValueError):
                rp._build_proforma_request_from_draft(
                    _draft("500", client_name="ZZ Nonexistent Slice3B Client")
                )
        cm.assert_not_called()


class TestThreadingWiring:
    def test_signature_unchanged_takes_only_draft(self):
        # The fix must NOT change the public signature — the draft (already the sole
        # arg) is the cid source. Guards against an accidental scope-expanding param.
        params = list(inspect.signature(rp._build_proforma_request_from_draft).parameters)
        assert params == ["draft"]

    def test_builder_threads_draft_cid_into_resolver(self):
        src = inspect.getsource(rp._build_proforma_request_from_draft)
        assert "_resolve_customer(" in src
        assert 'client_contractor_id=(getattr(draft, "client_contractor_id", "") or "")' in src

    def test_post_payload_contractor_id_is_resolver_output(self):
        src = inspect.getsource(rp._build_proforma_request_from_draft)
        assert 'contractor_id = resolution["wfirma_customer_id"]' in src


class TestNoRemovalNoScopeCreep:
    def test_no_name_fallback_branch_removed(self):
        src = inspect.getsource(rp._resolve_customer)
        assert "0-pre" in src
        assert "0a." in src
        assert "customer_master" in src.lower()
        assert "wfirma_customers" in src

    def test_builder_adds_no_customer_creation(self):
        src = inspect.getsource(rp._build_proforma_request_from_draft)
        for forbidden in ("create_customer(", "create_contractor(", "wfirma_create_customer"):
            assert forbidden not in src

    def test_builder_adds_no_reservation_logic(self):
        src = inspect.getsource(rp._build_proforma_request_from_draft)
        for forbidden in ("create_reservation(", "reservation_worker", "wfirma_reservation"):
            assert forbidden not in src

    def test_builder_adds_no_schema_or_ddl(self):
        src = inspect.getsource(rp._build_proforma_request_from_draft).upper()
        for forbidden in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE"):
            assert forbidden not in src
