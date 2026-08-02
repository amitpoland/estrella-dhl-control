"""test_settings_factory_contract.py — governance for the test-settings factory.

These tests protect the boundary that let the email_sender drift happen: they
fail when the shared factory stops agreeing with the real
``app.core.config.Settings`` contract, rather than letting a service test fail
later with an ``AttributeError`` thrown from inside production code.

Deliberately NOT asserted here: that every production field is given a value.
Services depend only on the fields they read, and pinning all 186 would clone
the production model into the test tree — the exact duplication this factory
exists to remove.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from settings_factory import UnknownSettingError, make_test_settings


def test_factory_returns_the_real_settings_model(tmp_path):
    """Not a stub, not a namespace, not a mock — the production class."""
    s = make_test_settings(tmp_path)
    assert isinstance(s, Settings)


def test_every_factory_default_is_a_real_settings_field(tmp_path):
    """The drift guard.

    If a production field this factory pins is renamed or removed, this fails
    immediately and names it, instead of surfacing as an unrelated service test
    breaking somewhere else.
    """
    s = make_test_settings(tmp_path)
    for field in ("environment", "storage_root", "smtp_user", "smtp_password"):
        assert field in Settings.model_fields, f"factory pins unknown field: {field}"
        assert hasattr(s, field)


def test_default_environment_is_not_production(tmp_path):
    """A shared helper must never hand out a production posture by default.

    Note "test" is not a legal value — Settings declares
    Literal["dev", "prod"] — so "dev" is the non-production default.
    """
    assert make_test_settings(tmp_path).environment == "dev"


def test_send_path_tests_must_opt_into_production(tmp_path):
    assert make_test_settings(tmp_path, environment="prod").environment == "prod"


def test_unknown_override_raises_instead_of_being_ignored(tmp_path):
    """Settings sets extra="ignore", so pydantic would silently swallow this."""
    with pytest.raises(UnknownSettingError, match="smpt_user"):
        make_test_settings(tmp_path, smpt_user="typo@example.com")   # transposed


def test_invalid_value_still_fails_through_the_real_contract(tmp_path):
    """The factory adds validation; it never removes any."""
    with pytest.raises(ValidationError):
        make_test_settings(tmp_path, environment="test")


def test_smtp_credentials_are_pinned_against_host_environment(tmp_path, monkeypatch):
    """A developer with SMTP_USER exported must not flip tests onto the send path."""
    monkeypatch.setenv("SMTP_USER", "real-account@estrellajewels.eu")
    monkeypatch.setenv("SMTP_PASSWORD", "real-app-password")

    s = make_test_settings(tmp_path)

    assert s.smtp_user is None
    assert s.smtp_password is None


def test_overrides_win_over_defaults(tmp_path):
    s = make_test_settings(tmp_path, smtp_user="u", smtp_password="p")
    assert (s.smtp_user, s.smtp_password) == ("u", "p")


def test_storage_root_is_the_test_sandbox(tmp_path):
    assert make_test_settings(tmp_path).storage_root == tmp_path
