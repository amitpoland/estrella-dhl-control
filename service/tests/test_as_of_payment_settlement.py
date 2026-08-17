"""As-of settlement: out-of-window payment still reduces outstanding."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app.services.accounting_analytics import build_portfolio_from_facts
from app.services import ledger_fact_universe as LFU


def _inv_xml(*, iid: str, date: str, gross: str = "100.00", due: str = "") -> str:
    due = due or date
    return (
        f"<invoice><id>{iid}</id><fullnumber>FV {iid}</fullnumber>"
        f"<type>normal</type><date>{date}</date><paymentdate>{due}</paymentdate>"
        f"<currency>EUR</currency><netto>{gross}</netto><brutto>{gross}</brutto>"
        f"<contractor><id>C1</id><name>Acme</name></contractor></invoice>"
    )


def _pay_xml(*, pid: str, invoice_id: str, value: str, date: str) -> str:
    return (
        f"<payment><id>{pid}</id><invoice><id>{invoice_id}</id></invoice>"
        f"<value>{value}</value><value_pln>0</value_pln><date>{date}</date>"
        f"<contractor><id>C1</id></contractor></payment>"
    )


def test_out_of_window_payment_still_reduces_outstanding():
    """Invoice in [from,to]; payment dated before from must still settle."""
    invoices = [
        {
            "id": "INV1",
            "fullnumber": "FV 1",
            "type": "normal",
            "date": "2026-06-15",
            "paymentdate": "2026-07-15",
            "currency": "EUR",
            "netto": Decimal("100.00"),
            "brutto": Decimal("100.00"),
            "contractor_id": "C1",
            "contractor_name": "Acme",
        }
    ]
    # Payment before the activity window lower bound.
    payments = [
        {
            "id": "PAY_EARLY",
            "linked_invoice": "INV1",
            "linked_expense": "",
            "value": Decimal("40.00"),
            "value_pln": Decimal("0"),
            "date": "2026-01-10",
            "currency_label": "",
            "currency": "",
            "contractor_id": "C1",
        }
    ]
    out = build_portfolio_from_facts(
        invoices,
        payments,
        as_of="2026-08-01",
        period=("2026-06-01", "2026-08-01"),
    )
    row = out["customers"][0]
    assert Decimal(row["outstanding"]) == Decimal("60.00")


def test_fact_universe_keeps_pre_window_payments():
    """load_ar_fact_universe fetches payments with empty floor through date_to."""
    LFU.clear_fact_universe_cache()
    inv = ET.fromstring(_inv_xml(iid="1", date="2026-06-15", gross="100.00"))
    pay_early = ET.fromstring(
        _pay_xml(pid="EARLY", invoice_id="1", value="25.00", date="2025-12-01")
    )
    pay_late = ET.fromstring(
        _pay_xml(pid="LATE", invoice_id="1", value="10.00", date="2026-09-01")
    )
    seen_pay_args = []

    def fake_inv(df, dt, types=(), stats=None):
        return [inv]

    def fake_pay(df, dt, stats=None):
        seen_pay_args.append((df, dt))
        return [pay_early, pay_late]

    with patch.object(LFU.wfirma_client, "fetch_invoices_for_period", side_effect=fake_inv), \
         patch.object(LFU.wfirma_client, "fetch_payments_for_period", side_effect=fake_pay):
        uni = LFU.load_ar_fact_universe("2026-06-01", "2026-08-01", force=True)

    assert seen_pay_args == [("", "2026-08-01")]
    pay_ids = {p["id"] for p in uni["payment_facts"]}
    assert "EARLY" in pay_ids
    assert "LATE" not in pay_ids  # after as_of_upper
    assert len(uni["invoice_facts"]) == 1
