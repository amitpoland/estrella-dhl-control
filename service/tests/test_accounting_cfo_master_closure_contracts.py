"""Currency Exposure / WH routing / MM honesty — campaign contract pins."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGERS = ROOT / "app" / "static" / "v2" / "ledgers-page.jsx"
HUB = ROOT / "app" / "static" / "v2" / "accounting-hub.jsx"
ROUTER = ROOT / "app" / "services" / "wfirma_webhook_event_router.py"


def test_currency_exposure_section_is_native_only_no_fx_merge():
    src = LEDGERS.read_text(encoding="utf-8")
    assert 'testid="ldg-ma-currency-exposure"' in src
    assert "Inventory exposure" in src
    assert "no inventory valuation authority" in src.lower() or "Unavailable — no inventory valuation" in src
    assert "Do not sum PLN+EUR+USD+CHF" in src or "Native currencies only" in src


def test_exceptions_include_ap_sync_and_webhook_watchdogs():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "ap-sync-stale-watchdog" in src
    assert "ap-sync-error" in src
    assert "wh009-events-without-processing" in src
    assert "getWfirmaWebhookStatus" in src


def test_mm_unsupported_not_backend_pending():
    src = HUB.read_text(encoding="utf-8")
    assert "mm-unsupported" in src
    assert "unsupported" in src.lower()
    assert "warehouse_document_m_m" in src


def test_hub_client_balance_uses_shared_clients_roster():
    src = HUB.read_text(encoding="utf-8")
    assert "listClientBalancesShared" in src
    assert 'testid="acc-balance"' in src
    assert "due-date aging" in src


def test_client_ledger_roster_not_live_wfirma_copy():
    src = LEDGERS.read_text(encoding="utf-8")
    assert "Loading client balances (local projection)" in src
    assert "Overdue (due-date)" in src


def test_router_documents_wh002_wh003_pending_no_mutation():
    src = ROUTER.read_text(encoding="utf-8")
    assert "DOMAIN_INVOICE_DELETE" in src
    assert "DOMAIN_PAYMENT" in src
    assert "tombstone pending" in src.lower() or "tombstone_pending" in src
    assert "payment_poll_sync" in src
    assert "OI-10" in src
