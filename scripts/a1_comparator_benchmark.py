#!/usr/bin/env python3
"""a1_comparator_benchmark.py — Campaign-2 A1.1 · performance benchmark.

Production reconciliation may run the comparator over thousands of invoices, so
this measures throughput and peak memory of a single comparison. Pure-stdlib
(time.perf_counter + tracemalloc). No external deps.

Usage: python scripts/a1_comparator_benchmark.py [iterations]
"""
from __future__ import annotations

import sys
import time
import tracemalloc
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))

from app.services.document_comparator import compare_invoice_plan  # noqa: E402
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem  # noqa: E402


def _plan(n_lines: int) -> FinalInvoicePlan:
    lines = [LineItem(name=f"ITEM{i}", good_id=str(i), unit="szt.",
                      unit_count="1.0000", price="100.00", vat_code_id="228")
             for i in range(n_lines)]
    return FinalInvoicePlan(
        type="normal", contractor_id="9001", currency="EUR",
        price_currency_exchange=None, paymentmethod="przelew",
        paymentdate="2026-05-15", date="2026-06-08", description="x",
        series_id="15827921", company_account_id="194483",
        translation_language_id=None, contractor_receiver_id="77",
        contents=lines, source_proforma_id="1", source_proforma_number="P/1",
        expected_total=Decimal("100.00") * n_lines,
    )


def _xml(n_lines: int, *, mismatch: bool) -> str:
    body = ""
    for i in range(n_lines):
        price = "999.00" if (mismatch and i == n_lines - 1) else "100.00"
        body += (f"<invoicecontent><name>ITEM{i}</name><good><id>{i}</id></good>"
                 f"<unit>szt.</unit><unit_count>1.0000</unit_count>"
                 f"<price>{price}</price><vat_code><id>228</id></vat_code>"
                 "</invoicecontent>")
    return ("<api><invoices><invoice><id>500001</id><type>normal</type>"
            "<currency>EUR</currency>"
            f"<total>{100 * n_lines}.00</total>"
            "<contractor><id>9001</id></contractor>"
            "<contractor_receiver><id>77</id></contractor_receiver>"
            f"<invoicecontents>{body}</invoicecontents></invoice></invoices></api>")


def _bench(label: str, plan, xml: str, iterations: int) -> None:
    # warmup
    for _ in range(1000):
        compare_invoice_plan(plan, xml)
    tracemalloc.start()
    t0 = time.perf_counter()
    for _ in range(iterations):
        compare_invoice_plan(plan, xml)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    per_op_us = (elapsed / iterations) * 1e6
    ops = iterations / elapsed
    print(f"{label:28s} iters={iterations:>7d}  "
          f"{per_op_us:8.2f} µs/op  {ops:12,.0f} ops/s  "
          f"peak={peak/1024:7.1f} KiB  10k≈{elapsed/iterations*10000:6.3f}s")


def main() -> int:
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    print("=== document_comparator.compare_invoice_plan benchmark ===")
    print(f"python {sys.version.split()[0]}  iterations={iterations}\n")
    for n in (1, 5, 25):
        _bench(f"match  ({n} line)", _plan(n), _xml(n, mismatch=False), iterations)
        _bench(f"mismatch ({n} line)", _plan(n), _xml(n, mismatch=True), iterations)
    print("\nInterpretation: a single comparison is pure in-memory XML parse +"
          " field compare; projected cost for 10,000 invoices shown per row.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
