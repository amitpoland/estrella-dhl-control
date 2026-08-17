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


def test_last_30d_is_documented_receipts_not_backend_pending():
    ledgers = LEDGERS.read_text(encoding="utf-8")
    hub = HUB.read_text(encoding="utf-8")
    routes = (ROOT / "app" / "api" / "routes_ledgers.py").read_text(encoding="utf-8")
    analytics = (ROOT / "app" / "services" / "accounting_analytics.py").read_text(
        encoding="utf-8"
    )
    assert "receipts_last_30d" in analytics
    assert '"last_30d":             "backend_pending"' not in routes
    assert "documented (matched payment receipts" in routes
    assert "Last 30d (receipts)" in ledgers
    assert "Applied receipts in last 30 calendar days" in hub
    assert "wh002-pending" in ledgers
    assert "wh003-pending" in ledgers
    assert "wh004-hard-block" in ledgers
    assert "formatLedgerWarning" in ledgers
    assert "Authority:" in ledgers
    assert "[object Object]" in ledgers  # guarded, never rendered raw
