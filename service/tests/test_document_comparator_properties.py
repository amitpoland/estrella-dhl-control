"""test_document_comparator_properties.py — Campaign-2 A1.1 · PROPERTY TESTS.

Hypothesis is not installed in this environment and installing it would mutate
the shared interpreter, so this is a deterministic, seeded property harness in
the same spirit: it generates thousands of plan/actual pairs and asserts
INVARIANTS rather than specific values.

Invariants pinned:
  P1  well-formed input never raises (pure, total function over valid XML)
  P2  result is always InvoiceComparisonResult
  P3  gaps appear in canonical matrix order (never reordered)
  P4  determinism — identical input yields identical gaps (fields + messages)
  P5  a faithfully-mirrored actual yields ZERO gaps
  P6  gate parity — _verify_created_invoice raises iff a blocking gap exists,
      and the raised message equals first_blocking_gap().message
"""
from __future__ import annotations

import random
from decimal import Decimal

from app.services.document_comparator import (
    compare_invoice_plan, InvoiceComparisonResult,
)
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem
from app.api.routes_proforma import _verify_created_invoice

SEED = 0xA11CE          # fixed seed → reproducible
ITERATIONS = 3000

# canonical matrix order → index for the ordering invariant (P3)
_ORDER = {
    "invoice": 0, "id": 1, "type": 2, "contractor_id": 3,
    "line_count": 4, "_line": 5, "currency": 6, "total": 7,
    "contractor_receiver_id": 8,
}


def _order_index(field: str) -> int:
    return _ORDER["_line"] if field.startswith("line[") else _ORDER[field]


def _rng_plan(rng) -> FinalInvoicePlan:
    n = rng.randint(1, 4)
    lines = [
        LineItem(
            name=rng.choice(["RING", "PENDANT", "CHAIN", "BR ACELET"]),
            good_id=str(rng.randint(1, 99)),
            unit="szt.",
            unit_count=f"{rng.randint(1, 9)}.0000",
            price=f"{rng.randint(1, 999)}.{rng.randint(0, 99):02d}",
            vat_code_id=rng.choice(["222", "228", "229"]),
        )
        for _ in range(n)
    ]
    total = sum(Decimal(l.price) * Decimal(l.unit_count) for l in lines)
    return FinalInvoicePlan(
        type="normal", contractor_id=str(rng.randint(1000, 9999)),
        currency=rng.choice(["EUR", "USD", "PLN"]),
        price_currency_exchange=None, paymentmethod="przelew",
        paymentdate="2026-05-15", date="2026-06-08", description="x",
        series_id="15827921", company_account_id="194483",
        translation_language_id=None,
        contractor_receiver_id=(str(rng.randint(1, 9999))
                                if rng.random() < 0.4 else None),
        contents=lines, source_proforma_id="1", source_proforma_number="P/1",
        expected_total=total,
    )


def _xml_from(plan: FinalInvoicePlan, *, faithful: bool, rng) -> str:
    """Build actual XML mirroring the plan, optionally perturbing fields."""
    def maybe(val, mutate):
        return mutate if (not faithful and rng.random() < 0.35) else val

    inv_type = maybe("normal", rng.choice(["proforma", "estimate", ""]))
    contractor = maybe(plan.contractor_id, str(rng.randint(1, 999)))
    currency = maybe(plan.currency, rng.choice(["EUR", "USD", "PLN", "GBP"]))
    total = maybe(str(plan.expected_total),
                  str(plan.expected_total + Decimal(rng.choice(["0.50", "5", "100"]))))
    rcv_expected = plan.contractor_receiver_id or ""
    rcv = maybe(rcv_expected, "" if rcv_expected else str(rng.randint(1, 99)))
    drop_line = (not faithful and rng.random() < 0.15)
    lines = plan.contents[:-1] if (drop_line and len(plan.contents) > 1) else plan.contents

    body = ""
    for l in lines:
        nm = maybe(l.name, "WRONG")
        gid = maybe(l.good_id, str(int(l.good_id or "0") + 1))
        uc = maybe(l.unit_count, "99.0000")
        pr = maybe(l.price, "0.01")
        vt = maybe(l.vat_code_id, "111")
        body += (f"<invoicecontent><name>{nm}</name><good><id>{gid}</id></good>"
                 f"<unit>szt.</unit><unit_count>{uc}</unit_count>"
                 f"<price>{pr}</price><vat_code><id>{vt}</id></vat_code>"
                 "</invoicecontent>")
    rcv_block = f"<contractor_receiver><id>{rcv}</id></contractor_receiver>" if rcv else ""
    return (
        "<api><invoices><invoice>"
        f"<id>500001</id><type>{inv_type}</type>"
        f"<currency>{currency}</currency><total>{total}</total>"
        f"<contractor><id>{contractor}</id></contractor>{rcv_block}"
        f"<invoicecontents>{body}</invoicecontents>"
        "</invoice></invoices></api>"
    )


def test_property_invariants_over_random_corpus():
    rng = random.Random(SEED)
    for i in range(ITERATIONS):
        plan = _rng_plan(rng)
        faithful = rng.random() < 0.35
        xml = _xml_from(plan, faithful=faithful, rng=rng)

        # P1 + P2: never raises; correct type
        res = compare_invoice_plan(plan, xml)
        assert isinstance(res, InvoiceComparisonResult)

        # P3: gaps in canonical matrix order
        idxs = [_order_index(g.field) for g in res.gaps]
        assert idxs == sorted(idxs), f"iter {i}: gaps out of order: {[g.field for g in res.gaps]}"

        # P4: determinism
        res2 = compare_invoice_plan(plan, xml)
        assert [(g.field, g.message) for g in res.gaps] == \
               [(g.field, g.message) for g in res2.gaps]

        # P5: a faithful mirror has no gaps
        if faithful:
            assert res.gaps == [], f"iter {i}: faithful mirror produced gaps"

        # P6: gate parity
        blocking = res.first_blocking_gap()
        if blocking is None:
            assert _verify_created_invoice(plan, xml) is None
        else:
            try:
                _verify_created_invoice(plan, xml)
            except RuntimeError as exc:
                assert str(exc) == blocking.message
            else:  # pragma: no cover
                raise AssertionError(f"iter {i}: gate did not raise for blocking gap")


def test_every_gap_is_classified():
    rng = random.Random(SEED + 1)
    seen = 0
    for _ in range(500):
        plan = _rng_plan(rng)
        res = compare_invoice_plan(plan, _xml_from(plan, faithful=False, rng=rng))
        for g in res.gaps:
            seen += 1
            assert g.severity in {"info", "warning", "critical"}
            assert g.resolution_policy in {
                "none", "local_projection_repair", "approval_required", "blocked"}
            assert g.evidence_quality in {
                "exact_remote_snapshot", "current_master_projection", "not_verifiable"}
            assert g.message  # non-empty
    assert seen > 0, "corpus produced no gaps to classify"
