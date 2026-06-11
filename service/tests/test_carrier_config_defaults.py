"""
Phase A gate test — carrier config fields have safe defaults.
No live calls. No DB. No HTTP.
"""
import pytest

from app.core.config import Settings


def test_carrier_api_status_default_is_pending():
    assert Settings().carrier_api_status == "pending"


def test_carrier_plt_status_default_is_pending():
    assert Settings().carrier_plt_status == "pending"


def test_carrier_live_allowlist_default_is_empty():
    assert Settings().carrier_live_allowlist == ""


def test_dhl_express_api_key_default_is_none():
    assert Settings().dhl_express_api_key is None


def test_dhl_express_api_secret_default_is_none():
    assert Settings().dhl_express_api_secret is None


def test_dhl_express_api_url_default():
    assert Settings().dhl_express_api_url == "https://express.api.dhl.com"


def test_dhl_express_account_number_default_is_none():
    assert Settings().dhl_express_account_number is None


def test_dhl_webhook_secret_default_is_none():
    assert Settings().dhl_webhook_secret is None


def test_carrier_storage_root_default_is_none():
    assert Settings().carrier_storage_root is None
