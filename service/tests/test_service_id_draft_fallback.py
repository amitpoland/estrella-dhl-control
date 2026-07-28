"""
test_service_id_draft_fallback.py

Draft-saved service-ID contextual fallback (advisory, read-only).

Background
----------
Customer Master is the canonical owner of freight/insurance service products
and amounts. A specific draft may already carry a valid wFirma service ID on its
saved charge line while Customer Master has no service ID configured. Previously
`pick_freight` / `compute_insurance_suggestion` blocked purely because the
Customer Master service ID was missing — so the advisory preview showed
"not configured" even though the draft held a valid service product. This is the
Draft #73 duplicated-authority symptom.

Resolution rule pinned here:
  1. Customer Master service ID           → service_id_source == "customer_master"
  2. same-draft saved service ID (fallback) → "saved_draft_fallback"
  3. neither                              → blocked, "unresolved"

Invariants:
  * The AMOUNT always comes from Customer Master. The draft fallback supplies the
    service *identity* only — never an amount. If the identity resolves via
    fallback but Customer Master has no amount for the currency, the call still
    blocks on the amount.
  * The fallback NEVER mutates the Customer Master record.
  * freight's saved ID can only satisfy freight; insurance's only insurance.
  * The explicit WRITE/apply path (`POST .../apply-service-charges`) resolves
    service identity with the SAME fixed order as the preview, so it never
    rejects an identity the preview accepted (no preview/execution split
    authority). Because a same-draft fallback ID can only exist when a charge of
    that type is ALREADY on the draft, the fallback case on Apply is an in-place
    amount update (amount from Customer Master, existing service identity
    preserved) — NOT a fresh auto-inserted charge, and NEVER a Customer Master
    write. Nothing is ever applied unless the operator explicitly selected that
    charge type and invoked Apply. See the apply-path tests below and
    test_proforma_customer_authority.py.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.customer_master import (  # noqa: E402
    pick_freight,
    compute_insurance_suggestion,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_cm(
    *,
    freight_fixed_amount_eur=None,
    freight_fixed_amount_usd=None,
    freight_service_id="13002743",
    insurance_service_id="13102217",
    insurance_rate=None,
    insurance_enabled=True,
    insurance_fixed_amount_eur=None,
    insurance_fixed_amount_usd=None,
):
    """Minimal CustomerMaster-like namespace covering the fields the two
    resolvers read. Mirrors the helper in
    test_suggest_freight_insurance_customer_authority.py."""
    def _d(x):
        return Decimal(str(x)) if x is not None else None
    return SimpleNamespace(
        # Identity fields read by the route's blocked-freight repair context
        # (_freight_authority_block deep-links the exact CM record to edit).
        bill_to_contractor_id="99001",
        bill_to_name="TestClient",
        freight_fixed_amount_eur=_d(freight_fixed_amount_eur),
        freight_fixed_amount_usd=_d(freight_fixed_amount_usd),
        freight_service_id=freight_service_id,
        freight_mode=None,
        freight_last_amount=None,
        freight_avg_amount=None,
        freight_currency=None,
        freight_label_pl=None,
        freight_label_en=None,
        insurance_service_id=insurance_service_id,
        insurance_rate=_d(insurance_rate),
        insurance_mode=None,
        insurance_enabled=insurance_enabled,
        insurance_fixed_amount_eur=_d(insurance_fixed_amount_eur),
        insurance_fixed_amount_usd=_d(insurance_fixed_amount_usd),
        insurance_min_eur=None,
        insurance_min_usd=None,
        insurance_min_amount=None,
        insurance_min_override=None,
        insurance_label_pl=None,
        insurance_label_en=None,
    )


# ── Freight: source labelling ────────────────────────────────────────────────

def test_freight_source_customer_master_when_cm_has_service_id():
    cm = _make_cm(freight_fixed_amount_usd=28, freight_service_id="13002743")
    r = pick_freight(cm, "USD", draft_service_id="99999999")
    assert r["ok"] is True
    # CM owns the ID → CM ID wins over the draft fallback, source is customer_master
    assert r["service_id_source"] == "customer_master"
    assert r["wfirma_service_id"] == "13002743"
    assert r["amount"] == Decimal("28")


def test_freight_source_saved_draft_fallback_when_cm_lacks_service_id():
    # Draft #73 shape: CM has the USD amount but NO freight_service_id; the draft
    # already carries service ID 13002743 on its saved freight charge.
    cm = _make_cm(freight_fixed_amount_usd=28, freight_service_id=None)
    r = pick_freight(cm, "USD", draft_service_id="13002743", draft_service_label="FedEx")
    assert r["ok"] is True
    assert r["service_id_source"] == "saved_draft_fallback"
    assert r["wfirma_service_id"] == "13002743"
    # Amount STILL comes from Customer Master, not the draft.
    assert r["amount"] == Decimal("28")
    # Label falls back to the draft-supplied label when CM has none.
    assert r["label"] == "FedEx"


def test_freight_unresolved_when_no_id_anywhere():
    cm = _make_cm(freight_fixed_amount_usd=28, freight_service_id=None)
    r = pick_freight(cm, "USD")  # no fallback supplied
    assert r["ok"] is False and r["blocked"] is True
    assert r["service_id_source"] == "unresolved"
    assert "freight_service_id" in r["reason"]


def test_freight_amount_always_from_cm_even_with_fallback_identity():
    # Identity resolves via fallback, but CM has NO USD amount → block on amount.
    cm = _make_cm(freight_fixed_amount_usd=None, freight_service_id=None)
    r = pick_freight(cm, "USD", draft_service_id="13002743")
    assert r["ok"] is False and r["blocked"] is True
    # The block is now about the missing AMOUNT, not the identity.
    assert r["field"] == "freight_fixed_amount_usd"
    assert r["service_id_source"] == "saved_draft_fallback"


def test_freight_fallback_does_not_mutate_customer_master():
    cm = _make_cm(freight_fixed_amount_usd=28, freight_service_id=None)
    pick_freight(cm, "USD", draft_service_id="13002743")
    # The fallback supplies identity for the response only — CM stays untouched.
    assert cm.freight_service_id is None


@pytest.mark.parametrize("bad_id", ["", "   ", "\t", None])
def test_freight_empty_or_malformed_draft_service_id_rejected(bad_id):
    # Contract req 6: an empty / whitespace-only / None saved ID is malformed and
    # must be REJECTED, never accepted as a fallback identity. The result stays
    # unresolved exactly as if no fallback had been supplied.
    cm = _make_cm(freight_fixed_amount_usd=28, freight_service_id=None)
    r = pick_freight(cm, "USD", draft_service_id=bad_id)
    assert r["ok"] is False and r["blocked"] is True
    assert r["service_id_source"] == "unresolved"
    assert "freight_service_id" in r["reason"]


def test_freight_padded_draft_service_id_is_stripped():
    # A padded-but-valid saved ID resolves to the clean SKU (not "  13002743  ").
    cm = _make_cm(freight_fixed_amount_usd=28, freight_service_id=None)
    r = pick_freight(cm, "USD", draft_service_id="  13002743  ")
    assert r["ok"] is True
    assert r["service_id_source"] == "saved_draft_fallback"
    assert r["wfirma_service_id"] == "13002743"


# ── Insurance: source labelling ──────────────────────────────────────────────

def test_insurance_source_customer_master_when_cm_has_service_id():
    cm = _make_cm(insurance_rate="0.0045", insurance_service_id="13102217")
    r = compute_insurance_suggestion(cm, "USD", Decimal("10000"), draft_service_id="88888888")
    assert r["ok"] is True
    assert r["service_id_source"] == "customer_master"
    assert r["wfirma_service_id"] == "13102217"


def test_insurance_source_saved_draft_fallback_when_cm_lacks_service_id():
    cm = _make_cm(insurance_rate="0.0045", insurance_service_id=None)
    r = compute_insurance_suggestion(
        cm, "USD", Decimal("10000"),
        draft_service_id="13102217", draft_service_label="Insurance",
    )
    assert r["ok"] is True
    assert r["service_id_source"] == "saved_draft_fallback"
    assert r["wfirma_service_id"] == "13102217"
    # Amount from the CM rate formula (0.45% of 10000 = 45), never the draft.
    assert r["amount"] == Decimal("45.00")


def test_insurance_unresolved_when_no_id_anywhere():
    cm = _make_cm(insurance_rate="0.0045", insurance_service_id=None)
    r = compute_insurance_suggestion(cm, "USD", Decimal("10000"))
    assert r["ok"] is False and r["blocked"] is True
    assert r["service_id_source"] == "unresolved"
    assert "insurance_service_id" in r["reason"]


def test_insurance_disabled_beats_fallback():
    # A disabled insurance is a genuine CM decision — the fallback must not
    # override it into an availability.
    cm = _make_cm(insurance_enabled=False, insurance_service_id=None)
    r = compute_insurance_suggestion(cm, "USD", Decimal("10000"), draft_service_id="13102217")
    assert r["ok"] is False and r["blocked"] is True
    assert "disabled" in r["reason"]


def test_insurance_amount_always_from_cm_even_with_fallback_identity():
    # Identity resolves via fallback but CM has no rate/fixed → block on amount.
    cm = _make_cm(insurance_rate=None, insurance_service_id=None)
    r = compute_insurance_suggestion(cm, "USD", Decimal("10000"), draft_service_id="13102217")
    assert r["ok"] is False and r["blocked"] is True
    assert r["service_id_source"] == "saved_draft_fallback"
    assert "no insurance amount configured" in r["reason"]


@pytest.mark.parametrize("bad_id", ["", "   ", "\t", None])
def test_insurance_empty_or_malformed_draft_service_id_rejected(bad_id):
    # Contract req 6, insurance side: an empty / whitespace-only / None saved ID
    # is malformed → rejected, stays unresolved.
    cm = _make_cm(insurance_rate="0.0045", insurance_service_id=None)
    r = compute_insurance_suggestion(cm, "USD", Decimal("10000"), draft_service_id=bad_id)
    assert r["ok"] is False and r["blocked"] is True
    assert r["service_id_source"] == "unresolved"
    assert "insurance_service_id" in r["reason"]


# ── Route-level: cross-type isolation + end-to-end wiring ─────────────────────

def _auth_headers():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key", "X-Operator": "alice"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_route_freight_fallback_does_not_leak_into_insurance(client):
    """A draft that saved ONLY a freight service ID must let freight resolve via
    fallback while insurance stays unresolved — the freight ID never satisfies
    insurance. Proves cross-type isolation through the real endpoint."""
    from app.api import routes_proforma

    cm = _make_cm(
        freight_fixed_amount_usd=28, freight_service_id=None,
        insurance_rate="0.0045", insurance_service_id=None,
    )
    draft = SimpleNamespace(
        id=73,
        service_charges_json=json.dumps([
            {"charge_type": "freight", "amount": "28.00", "currency": "USD",
             "wfirma_service_id": "13002743", "label": "FedEx"},
        ]),
        editable_lines_json=json.dumps([{"qty": 10, "unit_price": 1000}]),
    )

    with patch.object(routes_proforma, "_suggest_lookup",
                      return_value=(draft, "USD", cm, None)):
        r = client.get(
            "/api/v1/proforma/draft/73/suggest-service-charges",
            headers=_auth_headers(),
        )
    assert r.status_code == 200
    body = r.json()

    # Freight resolves via the draft-saved ID.
    assert body["freight"]["available"] is True
    assert body["freight"]["service_id_source"] == "saved_draft_fallback"
    assert body["freight"]["wfirma_service_id"] == "13002743"
    assert body["freight"]["amount"] == "28"

    # Insurance has NO saved insurance ID to fall back on → stays unresolved.
    # The freight ID must not satisfy it.
    assert body["insurance"]["available"] is False
    assert body["insurance"]["service_id_source"] == "unresolved"
    assert body["insurance"]["wfirma_service_id"] is None


def test_route_both_types_resolve_via_their_own_saved_ids(client):
    """When the draft carries both saved service IDs and CM has the amounts but
    no IDs, both charge types resolve via their own fallback."""
    from app.api import routes_proforma

    cm = _make_cm(
        freight_fixed_amount_usd=28, freight_service_id=None,
        insurance_rate="0.0045", insurance_service_id=None,
    )
    draft = SimpleNamespace(
        id=73,
        service_charges_json=json.dumps([
            {"charge_type": "freight", "amount": "28.00", "currency": "USD",
             "wfirma_service_id": "13002743", "label": "FedEx"},
            {"charge_type": "insurance", "amount": "45.00", "currency": "USD",
             "wfirma_service_id": "13102217", "label": "Insurance"},
        ]),
        editable_lines_json=json.dumps([{"qty": 10, "unit_price": 1000}]),
    )

    with patch.object(routes_proforma, "_suggest_lookup",
                      return_value=(draft, "USD", cm, None)):
        r = client.get(
            "/api/v1/proforma/draft/73/suggest-service-charges",
            headers=_auth_headers(),
        )
    body = r.json()
    assert body["freight"]["service_id_source"] == "saved_draft_fallback"
    assert body["freight"]["wfirma_service_id"] == "13002743"
    assert body["insurance"]["service_id_source"] == "saved_draft_fallback"
    assert body["insurance"]["wfirma_service_id"] == "13102217"
    # Both are already applied on the draft, so the UI shows them as applied.
    assert body["freight"]["already_applied"] is True
    assert body["insurance"]["already_applied"] is True


def test_route_insurance_fallback_does_not_leak_into_freight(client):
    """Reverse of the freight-leak test: a draft that saved ONLY an insurance
    service ID must let insurance resolve via fallback while freight stays
    unresolved — the insurance ID never satisfies freight. Pins cross-type
    isolation in both directions."""
    from app.api import routes_proforma

    cm = _make_cm(
        freight_fixed_amount_usd=28, freight_service_id=None,
        insurance_rate="0.0045", insurance_service_id=None,
    )
    draft = SimpleNamespace(
        id=73,
        service_charges_json=json.dumps([
            {"charge_type": "insurance", "amount": "45.00", "currency": "USD",
             "wfirma_service_id": "13102217", "label": "Insurance"},
        ]),
        editable_lines_json=json.dumps([{"qty": 10, "unit_price": 1000}]),
    )

    with patch.object(routes_proforma, "_suggest_lookup",
                      return_value=(draft, "USD", cm, None)):
        r = client.get(
            "/api/v1/proforma/draft/73/suggest-service-charges",
            headers=_auth_headers(),
        )
    assert r.status_code == 200
    body = r.json()

    # Insurance resolves via its own draft-saved ID.
    assert body["insurance"]["available"] is True
    assert body["insurance"]["service_id_source"] == "saved_draft_fallback"
    assert body["insurance"]["wfirma_service_id"] == "13102217"

    # Freight has NO saved freight ID to fall back on → stays unresolved.
    # The insurance ID must not satisfy it.
    assert body["freight"]["available"] is False
    assert body["freight"]["service_id_source"] == "unresolved"
    assert body["freight"]["wfirma_service_id"] is None


def test_route_preview_does_not_mutate_draft_service_charges(client):
    """Contract req 5 + 8: the advisory preview is read-only. The draft's saved
    charge rows must be byte-identical before and after the GET — no write path
    may run during a suggestion."""
    from app.api import routes_proforma

    cm = _make_cm(
        freight_fixed_amount_usd=28, freight_service_id=None,
        insurance_rate="0.0045", insurance_service_id=None,
    )
    saved_json = json.dumps([
        {"charge_type": "freight", "amount": "28.00", "currency": "USD",
         "wfirma_service_id": "13002743", "label": "FedEx"},
        {"charge_type": "insurance", "amount": "45.00", "currency": "USD",
         "wfirma_service_id": "13102217", "label": "Insurance"},
    ])
    draft = SimpleNamespace(
        id=73,
        service_charges_json=saved_json,
        editable_lines_json=json.dumps([{"qty": 10, "unit_price": 1000}]),
    )

    with patch.object(routes_proforma, "_suggest_lookup",
                      return_value=(draft, "USD", cm, None)):
        r = client.get(
            "/api/v1/proforma/draft/73/suggest-service-charges",
            headers=_auth_headers(),
        )
    assert r.status_code == 200
    # The draft's saved charges are unchanged by the read-only preview.
    assert draft.service_charges_json == saved_json
