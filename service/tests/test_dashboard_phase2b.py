"""
Phase 2-B source-grep tests for ProformaDraftPanel additions:
- preview button (btn-draft-preview)
- incoterm selector (select-draft-incoterm)
- insurance_eur input (input-draft-insurance-eur)
- onSaveIncoterm handler
- preview href pattern (/preview.html)
"""
import pathlib

DASHBOARD = pathlib.Path(__file__).parent.parent / "app" / "static" / "dashboard.html"


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_preview_button_exists():
    """btn-draft-preview data-testid must be present in dashboard.html."""
    assert 'btn-draft-preview' in _src(), (
        "Preview button with data-testid='btn-draft-preview' not found in dashboard.html"
    )


def test_incoterm_select_exists():
    """select-draft-incoterm data-testid must be present (incoterm inline edit)."""
    src = _src()
    assert 'incoterm' in src, (
        "No 'incoterm' reference found in dashboard.html"
    )
    assert 'select-draft-incoterm' in src, (
        "Incoterm <select> with data-testid='select-draft-incoterm' not found in dashboard.html"
    )


def test_insurance_eur_input_exists():
    """input-draft-insurance-eur data-testid must be present (insurance_eur inline edit)."""
    src = _src()
    assert 'insurance_eur' in src, (
        "No 'insurance_eur' reference found in dashboard.html"
    )
    assert 'input-draft-insurance-eur' in src, (
        "Insurance EUR <input> with data-testid='input-draft-insurance-eur' "
        "not found in dashboard.html"
    )


def test_onSaveIncoterm_handler_exists():
    """onSaveIncoterm callback must be defined in dashboard.html."""
    assert 'onSaveIncoterm' in _src(), (
        "onSaveIncoterm handler not found in dashboard.html"
    )


def test_preview_href_pattern():
    """/preview.html must appear as part of the preview link href."""
    assert '/preview.html' in _src(), (
        "'/preview.html' pattern not found in dashboard.html — "
        "preview link href not wired correctly"
    )
