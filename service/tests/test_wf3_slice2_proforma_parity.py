"""WF-3 Slice 2 — parity harness for the proforma canonical contractor.id branch.

The additive branch in routes_proforma._resolve_customer must be PARITY-SAFE:
it may only ECHO the operator-selected contractor.id (never a different id),
it must fire only when a contractor.id is supplied AND resolves, and any failure
must fall through to the pre-existing resolution chain unchanged. These tests pin
that invariant so the fiscal document can never be routed to an unselected
contractor by this change.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_proforma as rp  # noqa: E402


def _fake_record(name="Canonical Name", source="customer_master"):
    return {"contractor_id": "IGNORED-IN-BRANCH", "name": name,
            "nip": "PL999", "country": "PL", "source": source}


class TestCanonicalBranchEchoesSelection:

    def test_id_present_echoes_operator_selection(self):
        # batch_id=None skips the packing paths (0a/0b); the WF-3 branch fires.
        with patch.object(rp._cir, "resolve_by_contractor_id", return_value=_fake_record()):
            out = rp._resolve_customer("Some Typed Name", batch_id=None,
                                       client_contractor_id="777")
        assert out["found"] is True
        assert out["match_strategy"] == "contractor_id_canonical"
        assert out["wfirma_customer_id"] == "777"      # exactly the operator's selection

    def test_branch_never_returns_a_different_id(self):
        # Even if the resolver record carries other id-ish fields, the branch
        # echoes ONLY the supplied cid — it can never emit a different id.
        rec = _fake_record(source="wfirma_customer_mirror")
        rec["contractor_id"] = "999-DIFFERENT"
        with patch.object(rp._cir, "resolve_by_contractor_id", return_value=rec):
            out = rp._resolve_customer("X", batch_id=None, client_contractor_id="777")
        assert out["wfirma_customer_id"] == "777"

    def test_strengthens_cm_miss_via_mirror_source(self):
        # The value-add: id present in mirror/legacy (CM miss) now resolves to
        # the operator's selection instead of falling to name matching.
        with patch.object(rp._cir, "resolve_by_contractor_id",
                          return_value=_fake_record(source="legacy_wfirma_customers")):
            out = rp._resolve_customer("Renamed Co", batch_id=None,
                                       client_contractor_id="555")
        assert out["found"] is True and out["wfirma_customer_id"] == "555"
        assert "legacy_wfirma_customers" in out["advisory"]


class TestParityFallThrough:

    def test_no_cid_does_not_take_the_branch(self):
        # No contractor.id → branch skipped → identical to the pre-existing chain.
        # (wfdb not initialised in this test → name chain returns found=False.)
        with patch.object(rp._cir, "resolve_by_contractor_id") as m:
            out = rp._resolve_customer("Some Name", batch_id=None, client_contractor_id="")
        m.assert_not_called()
        assert out["match_strategy"] != "contractor_id_canonical"

    def test_unresolvable_cid_falls_through(self):
        # cid supplied but the canonical resolver finds nothing → branch must NOT
        # assert found; it falls through to the existing chain.
        with patch.object(rp._cir, "resolve_by_contractor_id", return_value=None):
            out = rp._resolve_customer("Some Name", batch_id=None, client_contractor_id="404")
        assert out["match_strategy"] != "contractor_id_canonical"

    def test_resolver_exception_falls_through_without_crash(self):
        with patch.object(rp._cir, "resolve_by_contractor_id",
                          side_effect=RuntimeError("db locked")):
            out = rp._resolve_customer("Some Name", batch_id=None, client_contractor_id="500")
        # No exception propagated; branch did not assert a canonical match.
        assert out["match_strategy"] != "contractor_id_canonical"


class TestAuthoritySeparation:

    def test_branch_uses_canonical_resolver_not_a_wfirma_customer_api(self):
        import inspect
        src = inspect.getsource(rp._resolve_customer)
        # The new branch resolves via the canonical resolver, never a wFirma API.
        assert "_cir.resolve_by_contractor_id(" in src
        for forbidden in (".search_customer(", ".fetch_contractor_by_id(", ".create_customer("):
            # (the branch itself must not introduce these; pre-existing chain is unchanged)
            assert src.count(forbidden) == 0 or "contractor_id_canonical" not in src.split(forbidden)[0][-400:]
