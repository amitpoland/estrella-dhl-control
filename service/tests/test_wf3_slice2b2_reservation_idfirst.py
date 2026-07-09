"""WF-3 Slice 2B-2 — reservation id-first customer resolution.

Pins the Gate-6 id-first helper (the live-reservation-write customer id source)
and the preview customer_match id-first branch. The invariant: the branch ECHOES
the operator-selected contractor.id and NEVER substitutes a different one; when no
id is present or it does not resolve, the pre-existing name-based behavior runs
unchanged.
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

from app.services import wfirma_reservation_create as wrc  # noqa: E402
from app.services import wfirma_reservation as wr          # noqa: E402


def _draft(cid):
    return {"client_contractor_id": cid}


def _rec(contractor_id="ANY", name="N", source="customer_master"):
    return {"contractor_id": contractor_id, "name": name, "nip": "", "country": "", "source": source}


# ── Gate 6 id-first helper (R1 — the live reservation write id source) ────────

class TestGate6IdFirst:

    def test_id_present_and_resolves_echoes_it(self):
        with patch.object(wrc._cir, "resolve_by_contractor_id", return_value=_rec()):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Some Name") == "777"

    def test_id_resolves_does_not_consult_name(self):
        with patch.object(wrc._cir, "resolve_by_contractor_id", return_value=_rec()), \
             patch.object(wrc.wfdb, "get_customer") as gm:
            wrc._resolve_gate6_customer_id(_draft("777"), "Some Name")
        gm.assert_not_called()

    def test_id_and_name_agree_returns_the_id(self):
        # name lookup would also return 777; helper returns 777 either way.
        with patch.object(wrc._cir, "resolve_by_contractor_id", return_value=_rec()), \
             patch.object(wrc.wfdb, "get_customer", return_value={"wfirma_customer_id": "777"}):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Acme") == "777"

    def test_never_substitutes_a_different_id(self):
        # resolver record carries a different contractor_id field — helper still
        # echoes the operator's supplied id, never the record's.
        with patch.object(wrc._cir, "resolve_by_contractor_id",
                          return_value=_rec(contractor_id="999-DIFFERENT", source="wfirma_customer_mirror")):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Acme") == "777"

    def test_id_present_but_resolver_missing_falls_back_to_name(self):
        with patch.object(wrc._cir, "resolve_by_contractor_id", return_value=None), \
             patch.object(wrc.wfdb, "get_customer", return_value={"wfirma_customer_id": "555"}):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Acme") == "555"

    def test_no_selection_uses_name_unchanged(self):
        with patch.object(wrc._cir, "resolve_by_contractor_id") as rc, \
             patch.object(wrc.wfdb, "get_customer", return_value={"wfirma_customer_id": "555"}):
            assert wrc._resolve_gate6_customer_id(_draft(""), "Acme") == "555"
        rc.assert_not_called()

    def test_id_only_resolves_becomes_reservation_ready(self):
        # name lookup fails (no mapping) but id resolves → helper returns the id,
        # so Gate 6 now passes (previously blocked as CUSTOMER_NOT_MAPPED).
        with patch.object(wrc._cir, "resolve_by_contractor_id",
                          return_value=_rec(source="legacy_wfirma_customers")), \
             patch.object(wrc.wfdb, "get_customer", return_value=None):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Renamed Co") == "777"

    def test_resolver_exception_falls_through_to_name(self):
        with patch.object(wrc._cir, "resolve_by_contractor_id", side_effect=RuntimeError("db locked")), \
             patch.object(wrc.wfdb, "get_customer", return_value={"wfirma_customer_id": "555"}):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Acme") == "555"

    def test_neither_resolves_returns_empty_blocks_gate6(self):
        with patch.object(wrc._cir, "resolve_by_contractor_id", return_value=None), \
             patch.object(wrc.wfdb, "get_customer", return_value=None):
            assert wrc._resolve_gate6_customer_id(_draft("777"), "Ghost") == ""


# ── payload / substitution safety ────────────────────────────────────────────

class TestPayloadSafety:

    def test_reservation_request_uses_helper_output_verbatim(self):
        # The live payload's contractor id is exactly the Gate-6 helper output —
        # no separate/alternate id is introduced between Gate 6 and submission.
        src = inspect.getsource(wrc.create_one_reservation)
        assert "wfirma_customer_id = _resolve_gate6_customer_id(draft, client_name)" in src
        assert "wfirma_contractor_id=wfirma_customer_id" in src

    def test_slice_touches_no_invoice_or_proforma_payload(self):
        src = inspect.getsource(wrc)
        for forbidden in ("invoicecontent", "invoices/add", "proforma", "create_proforma", "build_final_invoice"):
            assert forbidden not in src, f"reservation-create references a fiscal-invoice payload: {forbidden}"


# ── R2 preview customer_match id-first branch ────────────────────────────────

class TestPreviewIdFirst:

    def test_preview_branch_uses_resolver_and_only_sets_bool(self):
        # The preview id-first branch resolves the draft's contractor.id and only
        # flips customer_match (a bool) — it never assigns a contractor id, so it
        # cannot substitute an id on any downstream write.
        src = inspect.getsource(wr)
        assert "_cir.resolve_by_contractor_id(client_cid)" in src
        # the id-first block sets customer_match = True; it does not build/emit an id
        idx = src.find("_cir.resolve_by_contractor_id(client_cid)")
        window = src[idx - 200: idx + 200]
        assert "customer_match = True" in window


# ── authority separation ─────────────────────────────────────────────────────

class TestAuthoritySeparation:

    def test_gate6_helper_has_no_writes_or_wfirma_create(self):
        src = inspect.getsource(wrc._resolve_gate6_customer_id)
        for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", ".commit(",
                          "create_reservation(", "create_customer(", "search_customer(",
                          "fetch_contractor_by_id("):
            assert forbidden not in src, f"Gate-6 helper contains forbidden op: {forbidden}"

    def test_gate6_helper_echoes_only_the_supplied_id(self):
        src = inspect.getsource(wrc._resolve_gate6_customer_id)
        # returns draft_cid (the supplied id) on the id-first path — never a value
        # taken from the resolver record.
        assert "return draft_cid" in src
        assert 'rec[' not in src and '.get("contractor_id")' not in src
