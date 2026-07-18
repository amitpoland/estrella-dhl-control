#!/usr/bin/env python3
"""a1_comparator_coverage.py — Campaign-2 A1.1 · CUSTOM line metric + gate.

NOT standard coverage.py branch coverage. coverage.py / pytest-cov are not
installed (and installing into the shared interpreter is undesirable), so this
measures a CUSTOM metric with the stdlib only: AST enumerates executable-BODY
statement lines of document_comparator.py, and sys.settrace records which of
those lines a representative battery executes. It reports
executed-body-lines / executable-body-lines — a LINE metric, not branch coverage.

Exits non-zero if the custom line metric < 100%. Prints any missed lines.

Usage: python scripts/a1_comparator_coverage.py
"""
from __future__ import annotations

import ast
import sys
from decimal import Decimal
from pathlib import Path

SERVICE = Path(__file__).resolve().parent.parent / "service"
sys.path.insert(0, str(SERVICE))
MODULE = SERVICE / "app" / "services" / "document_comparator.py"

from app.services import document_comparator as dc  # noqa: E402
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem  # noqa: E402


def _executable_lines() -> set:
    """Statement lines inside functions (exclude defs/docstrings/module top)."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    lines = set()

    # def/class HEADER lines run at import time (before settrace is armed), so
    # they are not "executable during the battery" — count only body statements.
    _HEADERS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.stmt) and not isinstance(stmt, _HEADERS):
                    # skip pure docstring expressions
                    if isinstance(stmt, ast.Expr) and isinstance(
                            getattr(stmt, "value", None), ast.Constant) and \
                            isinstance(stmt.value.value, str):
                        continue
                    lines.add(stmt.lineno)
            self.generic_visit(node)

    V().visit(tree)
    return lines


def _plan(**kw):
    d = dict(type="normal", contractor_id="9001", currency="EUR",
             price_currency_exchange=None, paymentmethod="przelew",
             paymentdate="d", date="d", description="x", series_id="s",
             company_account_id="a", translation_language_id=None,
             contractor_receiver_id=None,
             contents=[LineItem("RING", "42", "szt.", "1.0000", "306.00", "228")],
             source_proforma_id="1", source_proforma_number="P/1",
             expected_total=Decimal("306.00"))
    d.update(kw)
    return FinalInvoicePlan(**d)


def _line_xml(**over):
    f = dict(name="RING", good_id="42", unit_count="1.0000", price="306.00", vat="228")
    f.update(over)
    return (f"<invoicecontent><name>{f['name']}</name><good><id>{f['good_id']}</id></good>"
            f"<unit>szt.</unit><unit_count>{f['unit_count']}</unit_count>"
            f"<price>{f['price']}</price><vat_code><id>{f['vat']}</id></vat_code></invoicecontent>")


def _inv(*, itype="normal", inv_id="1", contractor="9001", currency="EUR",
         total="306.00", receiver="", lines=None, contractor_node=True,
         omit_good=False, omit_vat=False):
    if lines is None:
        lines = [_line_xml()]
    if omit_good:
        lines = ["<invoicecontent><name>RING</name><unit>szt.</unit>"
                 "<unit_count>1.0000</unit_count><price>306.00</price>"
                 "<vat_code><id>228</id></vat_code></invoicecontent>"]
    if omit_vat:
        lines = ["<invoicecontent><name>RING</name><good><id>42</id></good>"
                 "<unit>szt.</unit><unit_count>1.0000</unit_count>"
                 "<price>306.00</price></invoicecontent>"]
    con = f"<contractor><id>{contractor}</id></contractor>" if contractor_node else ""
    rcv = f"<contractor_receiver><id>{receiver}</id></contractor_receiver>" if receiver else ""
    cur = f"<currency>{currency}</currency>" if currency is not None else ""
    return (f"<api><invoices><invoice><id>{inv_id}</id><type>{itype}</type>"
            f"{cur}<total>{total}</total>{con}{rcv}"
            f"<invoicecontents>{''.join(lines)}</invoicecontents></invoice></invoices></api>")


def _battery():
    """Exercise every branch of compare_invoice_plan + result helpers."""
    p = _plan()
    # match
    r = dc.compare_invoice_plan(p, _inv()); assert r.gaps == []
    r.has_blocking_gaps; r.first_blocking_gap()
    # no invoice element
    dc.compare_invoice_plan(p, "<api></api>")
    # empty id
    dc.compare_invoice_plan(p, _inv(inv_id=""))
    # wrong type
    dc.compare_invoice_plan(p, _inv(itype="proforma"))
    # contractor node missing + mismatch
    dc.compare_invoice_plan(p, _inv(contractor_node=False))
    dc.compare_invoice_plan(p, _inv(contractor="9999"))
    # line count mismatch (0 lines)
    dc.compare_invoice_plan(p, _inv(lines=[]))
    # per-line each field mismatch + good/vat node missing
    for over in ({"name": "X"}, {"good_id": "9"}, {"unit_count": "9.0"},
                 {"price": "1.00"}, {"vat": "1"}):
        dc.compare_invoice_plan(p, _inv(lines=[_line_xml(**over)]))
    dc.compare_invoice_plan(p, _inv(omit_good=True))
    dc.compare_invoice_plan(p, _inv(omit_vat=True))
    # currency mismatch + currency absent
    dc.compare_invoice_plan(p, _inv(currency="USD"))
    dc.compare_invoice_plan(p, _inv(currency=None))
    # total drift + invalid decimal (hits except InvalidOperation)
    dc.compare_invoice_plan(p, _inv(total="500.00"))
    dc.compare_invoice_plan(p, _inv(total="notanumber"))
    # receiver expected+mismatch, expected+match, node missing
    pr = _plan(contractor_receiver_id="77")
    dc.compare_invoice_plan(pr, _inv(receiver=""))
    dc.compare_invoice_plan(pr, _inv(receiver="77"))
    # a blocking result to exercise first_blocking_gap loop 'return g'
    dc.compare_invoice_plan(p, _inv(contractor="9999")).first_blocking_gap()
    # a clean result to exercise 'return None' path
    dc.compare_invoice_plan(p, _inv()).first_blocking_gap()


def main() -> int:
    executable = _executable_lines()
    executed = set()
    modfile = str(MODULE)

    def tracer(frame, event, arg):
        if event == "line" and frame.f_code.co_filename == modfile:
            executed.add(frame.f_lineno)
        return tracer

    sys.settrace(tracer)
    try:
        _battery()
    finally:
        sys.settrace(None)

    covered = executable & executed
    missed = sorted(executable - executed)
    pct = 100.0 * len(covered) / len(executable) if executable else 100.0
    print("=== document_comparator.py CUSTOM line metric "
          "(stdlib trace + AST; NOT coverage.py branch coverage) ===")
    print(f"executable-body statement lines: {len(executable)}")
    print(f"executed-body lines:             {len(covered)}")
    print(f"custom line metric:              {pct:.1f}%")
    if missed:
        print(f"MISSED lines: {missed}")
        return 1
    print(f"{pct:.1f}% under the custom stdlib trace + AST executable-body line "
          f"metric ({len(covered)}/{len(executable)}). Standard coverage.py "
          f"branch coverage was NOT measured (coverage.py unavailable; no package "
          f"installed into the shared interpreter).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
