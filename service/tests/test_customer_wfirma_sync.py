# service/tests/test_customer_wfirma_sync.py
"""
Tests for Customer Master to wFirma contractor sync with verify.
Tests MUST FAIL until customer_sync.py is created (Task 10).
Run: cd service && pytest tests/test_customer_wfirma_sync.py -v
"""
import pytest
from unittest.mock import MagicMock


def test_sync_stores_sync_status():
    """
    Given: customer is pushed to wFirma
    When: sync_customer_to_wfirma() is called
    Then: result['sync_status'] is 'synced', 'mismatch', or 'failed'
    NOT empty/None (silent sync is forbidden)
    """
    from app.services.customer_sync import sync_customer_to_wfirma

    cm = MagicMock()
    cm.wfirma_contractor_id = "12345"
    cm.name = "OMARA s.r.o"
    cm.vat_id = "CZ12345678"

    mock_wfirma = MagicMock()
    mock_wfirma.push_contractor.return_value = {"ok": True}
    mock_wfirma.get_contractor.return_value = {
        "name": "OMARA s.r.o",
        "nip": "CZ12345678",
    }

    result = sync_customer_to_wfirma(cm, wfirma_client=mock_wfirma)
    assert result["sync_status"] in ("synced", "mismatch", "failed")


def test_sync_detects_mismatch():
    """
    Given: wFirma returns contractor with different name
    When: sync verify runs
    Then: sync_status == 'mismatch'
    And:  result['mismatches'] contains {'field': 'name', ...}
    """
    from app.services.customer_sync import sync_customer_to_wfirma

    cm = MagicMock()
    cm.wfirma_contractor_id = "12345"
    cm.name = "OMARA s.r.o"
    cm.vat_id = "CZ12345678"

    mock_wfirma = MagicMock()
    mock_wfirma.push_contractor.return_value = {"ok": True}
    mock_wfirma.get_contractor.return_value = {
        "name": "OMARA sro",   # different — missing dot
        "nip": "CZ12345678",
    }

    result = sync_customer_to_wfirma(cm, wfirma_client=mock_wfirma)
    assert result["sync_status"] == "mismatch"
    fields = [m["field"] for m in result["mismatches"]]
    assert "name" in fields


def test_sync_reports_synced_when_fields_match():
    """
    Given: wFirma returns contractor that matches Customer Master exactly
    When: sync verify runs
    Then: sync_status == 'synced' and mismatches == []
    """
    from app.services.customer_sync import sync_customer_to_wfirma

    cm = MagicMock()
    cm.wfirma_contractor_id = "12345"
    cm.name = "OMARA s.r.o"
    cm.vat_id = "CZ12345678"

    mock_wfirma = MagicMock()
    mock_wfirma.push_contractor.return_value = {"ok": True}
    mock_wfirma.get_contractor.return_value = {
        "name": "OMARA s.r.o",
        "nip": "CZ12345678",
    }

    result = sync_customer_to_wfirma(cm, wfirma_client=mock_wfirma)
    assert result["sync_status"] == "synced"
    assert result["mismatches"] == []
