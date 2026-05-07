"""
test_ai_parser_config.py — pin the ai_parser_model default + getattr fallback.

The previous default `claude-sonnet-4-20250514` did not match any current
Anthropic model identifier and caused HTTP 400 invalid_request_error from
the AI fallback path. This test pins the default to a current Sonnet 4.x
ID and asserts the two declaration sites stay in sync.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


_EXPECTED_DEFAULT = "claude-sonnet-4-6"


def test_settings_ai_parser_model_default_is_current_sonnet():
    """Pydantic Settings Field default for ai_parser_model must be a
    current Anthropic Sonnet 4.x identifier."""
    from app.core.config import Settings
    # Construct a fresh Settings instance with no env override so the
    # Field default is what we observe.
    s = Settings()
    assert s.ai_parser_model == _EXPECTED_DEFAULT, (
        f"ai_parser_model default drift: got {s.ai_parser_model!r}, "
        f"expected {_EXPECTED_DEFAULT!r}. Update both config.py:79 and "
        f"ai_customs_parser.py:82 together."
    )


def test_ai_customs_parser_getattr_fallback_matches_settings_default():
    """The hardcoded fallback in ai_customs_parser.py:82 must match the
    Pydantic Settings default. Drift between the two declaration sites
    is the failure mode this test prevents."""
    import inspect
    from app.services import ai_customs_parser
    src = inspect.getsource(ai_customs_parser)
    expected_line = (
        f'model = getattr(settings, "ai_parser_model", "{_EXPECTED_DEFAULT}")'
    )
    assert expected_line in src, (
        f"ai_customs_parser.py getattr fallback drift: expected the "
        f"fallback string {_EXPECTED_DEFAULT!r}. If the canonical default "
        f"changed, update BOTH config.py:79 and ai_customs_parser.py:82."
    )


def test_ai_parser_model_default_is_not_legacy_string():
    """Regression: the legacy default 'claude-sonnet-4-20250514' must NOT
    be the active default anywhere. That string returned 400
    invalid_request_error from Anthropic."""
    from app.core.config import Settings
    s = Settings()
    assert s.ai_parser_model != "claude-sonnet-4-20250514"

    import inspect
    from app.services import ai_customs_parser
    src = inspect.getsource(ai_customs_parser)
    assert '"claude-sonnet-4-20250514"' not in src, (
        "Legacy model ID still present in ai_customs_parser.py — "
        "remove it from the getattr fallback."
    )
